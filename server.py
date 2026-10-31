"""CoDraw LAN prototype: Bully election + all-view durable ordered delivery.

Assumptions and failure boundaries are documented in docs/PROTOCOL.md.
This is not Raft and is not a partition-tolerant consensus implementation.
"""
import argparse
import asyncio
from collections import deque
import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import math
from pathlib import Path
import re
import time
import uuid

from aiohttp import web, ClientSession, ClientTimeout, ClientError
import discovery
from log_store import LogStore, digest

ROOT = Path(__file__).resolve().parent


def validate_op(op):
    if not isinstance(op, dict):
        raise ValueError('Operation must be an object')
    if op.get('kind') not in {'STROKE', 'CLEAR'}:
        raise ValueError('Unknown operation kind')
    for key in ('op_id', 'client_id'):
        if not isinstance(op.get(key), str) or not 1 <= len(op[key]) <= 120:
            raise ValueError('Invalid ' + key)
    data = op.get('data')
    if op['kind'] == 'STROKE':
        if not isinstance(data, dict) or not re.fullmatch(r'#[0-9a-fA-F]{6}', str(data.get('color'))):
            raise ValueError('Invalid stroke colour')
        width = data.get('width')
        if isinstance(width, bool) or not isinstance(width, (float, int)) or not 1 <= width <= 60:
            raise ValueError('Invalid stroke width')
        points = data.get('points')
        if not isinstance(points, list) or not 1 <= len(points) <= 6000:
            raise ValueError('A stroke needs 1..6000 points')
        for p in points:
            if not isinstance(p, list) or len(p) != 2:
                raise ValueError('Invalid point')
            for x, bound in zip(p, (1000, 600)):
                if isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or not 0 <= x <= bound:
                    raise ValueError('Point outside canvas')
        data = {'color': data['color'], 'width': width, 'points': points}
    else:
        data = None
    return {k: op[k] for k in ('kind', 'op_id', 'client_id')} | {'data': data}


class Node:
    def __init__(self, args):
        self.args = args
        self.id = args.id
        self.url = f'http://{args.advertise}:{args.port}'
        self.boot = uuid.uuid4().hex
        self.store = LogStore(Path(args.data_dir) / 'operations.jsonl')
        self.peers = {}
        self.seeds = set(args.seed)
        self.clients = set()
        self.lock = asyncio.Lock()
        self.role = 'discovering'
        self.leader = None
        self.session = None
        self.view = []
        self.ready = False
        self.events = deque(maxlen=80)
        self.tasks = set()
        self.revision = 0
        self.stable = 0
        self.last_members = ()
        self.drop_once = False
        self.delay_once = 0
        self.offline_until = 0
        self.was_offline = False
        self.id_conflict = False
        self.storage_failed = False
        self.probe_errors = {}
        self.last_health = 0
        self.event('START', f'Node {self.id}: loaded {len(self.store.entries)} entries')
        if self.store.repaired_tail_bytes:
            self.event('TORN WRITE REPAIRED', f'{self.store.repaired_tail_bytes} incomplete bytes saved as .torn; replayed complete records only.')

    def event(self, kind, message):
        self.events.append({'time': time.strftime('%H:%M:%S'), 'kind': kind, 'message': message})
        logging.info('NODE %s | %-18s | %s', self.id, kind, message)

    def storage_error(self, exc):
        self.storage_failed = True
        self.ready = False
        self.role = 'STORAGE ERROR'
        self.event('STORAGE ERROR', f'{exc}; writes halted. Preserve files, fix disk access and restart this node.')

    def offline(self):
        return time.monotonic() < self.offline_until

    async def control(self, command, seconds=0):
        if command == 'status':
            self.event('STATUS', f'role={self.role}, leader={self.leader}, ready={self.ready}, '
                       f'live={self.members()}, stored={len(self.store.entries)}, committed={self.store.committed}')
        elif command == 'peers':
            for n in self.status()['nodes']:
                self.event('PEER', f"Node {n['id']} | {n['url']} | {'ONLINE' if n['online'] else 'OFFLINE'} | {n['role']}")
        elif command == 'drop':
            self.drop_once = True
            self.event('FAULT ARMED', 'Next PREPARE will be rejected. Draw on a client to trigger it.')
        elif command == 'delay':
            self.delay_once = max(.1, min(float(seconds), 30))
            self.event('FAULT ARMED', f'Next PREPARE delayed {self.delay_once}s; peers will time out and recover.')
        elif command == 'offline':
            self.offline_until = time.monotonic() + max(1, min(float(seconds), 120))
            self.ready = False
            self.event('NETWORK SIMULATION', f'Peer communication and writes disabled for {seconds}s; local status stays visible.')
        elif command == 'online':
            self.offline_until = 0
            self.ready = False
            self.event('NETWORK RESTORED', 'Communication restored; synchronisation is required before writes resume.')
        elif command == 'election':
            self.ready = False
            self.leader = None
            self.event('ELECTION REQUEST', 'Manual election requested; normal Bully rules still select the highest ID.')
        elif command == 'crash':
            self.event('CRASH SIMULATION', 'Exiting immediately WITHOUT graceful cleanup. Restart with the same data directory.')
            for handler in logging.getLogger().handlers:
                handler.flush()
            os._exit(77)
        else:
            raise ValueError('Commands: status, peers, drop, delay SECONDS, offline SECONDS, online, election, crash')

    def identity(self):
        return {'id': self.id, 'url': self.url, 'boot': self.boot}

    def learn(self, p):
        if type(p.get('id')) is not int or p['id'] < 1 or not isinstance(p.get('url'), str):
            raise ValueError('Bad peer')
        if not re.fullmatch(r'http://[a-zA-Z0-9.\-]+:[0-9]{1,5}', p['url']):
            raise ValueError('Bad peer address')
        if p['id'] == self.id:
            if p['url'] != self.url:
                self.ready = False
                self.role = 'ID CONFLICT'
                self.id_conflict = True
                self.event('ERROR', 'Another process uses this server ID; assign unique IDs')
            return
        old = self.peers.get(p['id'])
        if old and old['url'] != p['url'] and time.monotonic() - old.get('seen', 0) < 3:
            raise ValueError('Duplicate peer ID')
        if not old or old['url'] != p['url']:
            self.peers[p['id']] = p | {'seen': 0, 'ready': False}
            self.event('DISCOVERY', f"Found node {p['id']} at {p['url']}")

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def rpc_url(self, url, message):
        if self.offline():
            raise RuntimeError('Local network interruption simulation active')
        async with self.http.post(url + '/rpc', json=message | {'sender': self.identity(), 'cluster': self.args.cluster},
                                  headers={'X-CoDraw-Token': self.args.token}) as r:
            value = await r.json()
            if r.status != 200 or not value.get('ok'):
                raise RuntimeError(value.get('error', 'Peer rejected message'))
            return value

    async def rpc(self, peer_id, message):
        kind = message['type']
        seq = message.get('seq', message.get('entry', {}).get('seq', '-'))
        self.event('SEND ' + kind, f'Node {self.id} -> Node {peer_id}, seq={seq}')
        try:
            result = await self.rpc_url(self.peers[peer_id]['url'], message)
            self.event('REPLY ' + kind, f'Node {peer_id} -> Node {self.id}: acknowledged')
            return result
        except Exception as exc:
            self.event('RPC FAILED', f'{kind} to Node {peer_id}: {type(exc).__name__}: {exc}')
            raise

    async def all_rpc(self, ids, message):
        results = await asyncio.gather(*(self.rpc(i, message) for i in ids), return_exceptions=True)
        failures = [str(i) for i, r in zip(ids, results) if isinstance(r, Exception)]
        if failures:
            self.event('REPLICATION PAUSED', 'Missing replies from nodes ' + ', '.join(failures) + '; no new writes until recovery.')
            raise RuntimeError('Missing acknowledgement from ' + ', '.join(failures))
        return results

    def members(self):
        now = time.monotonic()
        return tuple(sorted([self.id] + [i for i, p in self.peers.items() if now - p['seen'] < self.args.failure_timeout]))

    async def heartbeat(self, url):
        try:
            r = await self.rpc_url(url, {'type': 'HELLO'})
            p = r['node']
            old = self.peers.get(p['id'], {})
            previously_seen, old_boot = old.get('seen', 0), old.get('boot')
            self.learn(p)
            if p['id'] != self.id:
                if previously_seen and (time.monotonic() - previously_seen >= self.args.failure_timeout or old_boot != p['boot']):
                    self.event('PEER RETURNED', f"Node {p['id']} is reachable again; its log must catch up.")
                self.peers[p['id']].update(p | {'seen': time.monotonic(), 'ready': r['ready'], 'leader': r['leader']})
            self.probe_errors.pop(url, None)
            if self.args.trace_heartbeats:
                self.event('HEARTBEAT OK', f"Node {p['id']} answered; leader={r['leader']} ready={r['ready']}")
            for peer in r['peers']:
                self.learn(peer)
        except Exception as exc:
            self.probe_errors[url] = self.probe_errors.get(url, 0) + 1
            if self.probe_errors[url] == 1:
                self.event('HEARTBEAT MISSED', f'{url}: {type(exc).__name__} {exc}. Retrying; not yet declaring failure.')

    async def tick(self):
        while True:
            try:
                if self.storage_failed:
                    await self.broadcast({'type': 'STATUS', **self.status()})
                    await asyncio.sleep(self.args.heartbeat)
                    continue
                if self.id_conflict:
                    self.ready = False
                    self.role = 'ID CONFLICT'
                    await self.broadcast({'type': 'STATUS', **self.status()})
                    await asyncio.sleep(self.args.heartbeat)
                    continue
                if self.offline():
                    self.was_offline = True
                    self.ready = False
                    self.role = 'network offline (simulated)'
                    await self.broadcast({'type': 'STATUS', **self.status()})
                    await asyncio.sleep(self.args.heartbeat)
                    continue
                if self.was_offline:
                    self.was_offline = False
                    self.ready = False
                    self.last_members = ()
                    self.event('NETWORK RESTORED', 'Re-probing peers; stale state will be reconciled before drawing resumes.')
                if self.discovery:
                    self.discovery.announce()
                urls = self.seeds | {p['url'] for p in self.peers.values()}
                await asyncio.gather(*(self.heartbeat(u) for u in urls if u != self.url))
                members = self.members()
                if members != self.last_members:
                    lost = set(self.last_members) - set(members)
                    for node_id in sorted(lost):
                        label = 'LEADER SUSPECTED' if node_id == self.leader else 'FOLLOWER SUSPECTED'
                        self.event(label, f'Node {node_id} exceeded heartbeat timeout. Countermeasure: pause, elect, synchronise.')
                    self.last_members = members
                    self.stable = time.monotonic()
                    self.ready = False
                    self.event('MEMBERSHIP', f'Live IDs: {members}; pausing for recovery')
                if time.monotonic() - self.stable > self.args.settle:
                    if len(members) < self.args.min_nodes:
                        self.ready = False
                        if self.role != 'waiting for peers':
                            self.event('WRITES BLOCKED', f'Only {len(members)} live node(s); need {self.args.min_nodes}. Pending drawings are retained by clients.')
                        self.role = 'waiting for peers'
                    elif max(members) == self.id:
                        if not self.ready or any(not self.peers[i].get('ready') for i in members if i != self.id):
                            await self.elect(members)
                    else:
                        self.ready = self.ready and self.leader == max(members)
                        if self.leader != max(members):
                            self.role = 'electing'
                            self.event('ELECTION START', 'Sending ELECTION to higher IDs; waiting for COORDINATOR announcement.')
                            higher = [i for i in members if i > self.id]
                            await asyncio.gather(*(self.rpc(i, {'type': 'ELECTION'}) for i in higher), return_exceptions=True)
                            self.leader = max(members)
                if time.monotonic() - self.last_health > 10:
                    self.last_health = time.monotonic()
                    self.event('HEALTH', f'role={self.role}, leader={self.leader}, live={members}, confirmed={self.store.committed}')
                await self.broadcast({'type': 'STATUS', **self.status()})
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                self.storage_error(exc)
            except Exception as exc:
                self.ready = False
                self.role = 'recovery paused'
                self.event('RECOVERY RETRY', f'{exc}; retaining logs and retrying after next heartbeat round.')
            await asyncio.sleep(self.args.heartbeat)

    async def elect(self, members):
        async with self.lock:
            if self.role == 'ID CONFLICT':
                return
            self.ready = False
            self.role = 'electing'
            # Bully: inquire of all known higher IDs, including suspected failures.
            higher = [i for i in self.peers if i > self.id]
            self.event('ELECTION START', f'Checking known higher IDs {higher}; live view={members}')
            replies = await asyncio.gather(*(self.rpc(i, {'type': 'ELECTION'}) for i in higher), return_exceptions=True)
            if any(not isinstance(r, Exception) for r in replies):
                self.event('ELECTION WAIT', 'Higher-ID server answered; waiting for it to coordinate.')
                return
            self.session = f'{self.id}:{uuid.uuid4().hex}'
            self.leader = self.id
            self.view = list(members)
            others = [i for i in members if i != self.id]
            self.event('ELECTION', f'Bully winner {self.id}; recovering session {self.session[:12]}')
            snapshots = await self.all_rpc(others, {'type': 'COORDINATOR', 'session': self.session, 'view': self.view})
            histories = [self.store.snapshot()] + [r['snapshot'] for r in snapshots]
            longest = max(histories, key=lambda s: (s['committed'], len(s['entries'])))['entries']
            if any(longest[:s['committed']] != s['entries'][:s['committed']] for s in histories):
                raise RuntimeError('Conflicting histories: refusing to merge; see protocol guide')
            self.event('RECOVERY COMPARE', 'Collected (stored, committed): ' + str([(len(h['entries']), h['committed']) for h in histories]))
            self.event('RECOVERY PLAN', f'Preserve confirmed prefixes; install {len(longest)} entries on view {self.view}.')
            self.store.install(longest)
            await self.all_rpc(others, {'type': 'SYNC', 'session': self.session, 'entries': longest})
            if self.offline() or self.members() != members:
                raise RuntimeError('Membership changed during recovery')
            # Complete any durable prepared tail, preserving previously delivered prefixes.
            await self.all_rpc(others, {'type': 'APPLY', 'session': self.session, 'seq': len(longest)})
            self.store.commit(len(longest))
            self.role = 'leader'
            self.ready = True
            await self.snapshot_clients()
            self.event('READY', f'Leader {self.id}; {len(longest)} operations recovered')

    def status(self):
        live = self.members()
        nodes = [self.identity() | {'online': True, 'role': self.role}]
        nodes += [dict(id=i, url=p['url'], online=i in live,
                       role='leader' if i == self.leader else 'follower') for i, p in sorted(self.peers.items())]
        return {'node_id': self.id, 'leader': self.leader, 'role': self.role, 'ready': self.ready,
                'committed': self.store.committed, 'stored': len(self.store.entries),
                'cluster': self.args.cluster, 'url': self.url, 'clients': len(self.clients), 'session': self.session, 'nodes': nodes,
                'hash': digest(self.store.entries[:self.store.committed]), 'events': list(self.events)[-15:]}

    async def broadcast(self, message):
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_json(message), 1)
            except Exception:
                self.clients.discard(ws)
                self.spawn(ws.close())

    async def snapshot_clients(self):
        self.revision += 1
        await self.broadcast({'type': 'INIT', 'entries': self.store.entries[:self.store.committed]})

    async def submit(self, value):
        op = validate_op(value)
        if self.offline() or not self.ready:
            self.event('CLIENT QUEUED', 'Cannot confirm operation during election/recovery. Client retains it for retry.')
            raise RuntimeError('Election / recovery in progress; operation remains pending')
        if self.leader != self.id:
            self.event('FORWARD', f"Client {op['client_id']} -> leader {self.leader}; operation={op['kind']}")
            result = await self.rpc(self.leader, {'type': 'FORWARD', 'op': op})
            return result['entry']
        async with self.lock:
            if not self.ready or self.leader != self.id:
                raise RuntimeError('Leader changed; retry')
            existing = self.store.by_op_id.get(op['op_id'])
            if existing:
                if any(existing[k] != op[k] for k in op):
                    raise ValueError('Operation ID reused with different content')
                if existing['seq'] <= self.store.committed:
                    self.event('DUPLICATE SUPPRESSED', f"Operation already confirmed at #{existing['seq']}; returning original result.")
                    return existing
                raise RuntimeError('Prepared operation awaiting recovery')
            members = tuple(self.view)
            if self.members() != members:
                self.ready = False
                raise RuntimeError('Membership changed; retry after recovery')
            entry = op | {'seq': len(self.store.entries) + 1, 'session': self.session}
            others = [i for i in members if i != self.id]
            try:
                self.store.append(entry)
            except OSError as exc:
                self.storage_error(exc)
                raise
            self.event('LOCAL PERSIST', f"Stored #{entry['seq']} {entry['kind']}; sending PREPARE to {others}")
            try:
                await self.all_rpc(others, {'type': 'PREPARE', 'session': self.session, 'entry': entry})
                if self.offline() or self.members() != members or not self.ready:
                    raise RuntimeError('Membership changed during replication')
                await self.all_rpc(others, {'type': 'APPLY', 'session': self.session, 'seq': entry['seq']})
                self.store.commit(entry['seq'])
                self.revision += 1
                await self.broadcast({'type': 'COMMIT', 'entry': entry})
                self.event('COMMIT', f"#{entry['seq']} {entry['kind']} replicated on {len(members)} nodes")
                return entry
            except OSError as exc:
                self.storage_error(exc)
                raise
            except Exception as exc:
                self.event('COUNTERMEASURE', f'Replication interrupted: {exc}. Keep durable log, pause writes, recover before retry.')
                self.ready = False
                self.role = 'recovering'
                raise

    async def rpc_handler(self, request):
        if request.headers.get('X-CoDraw-Token') != self.args.token:
            raise web.HTTPForbidden()
        try:
            if self.storage_failed:
                raise RuntimeError('Storage failed; node cannot safely acknowledge messages')
            if self.offline():
                raise RuntimeError('Node temporarily offline (simulation)')
            m = await request.json()
            if m.get('cluster') != self.args.cluster:
                raise ValueError('Cluster name mismatch')
            sender = m['sender']; self.learn(sender)
            kind = m['type']
            if kind == 'HELLO':
                return web.json_response({'ok': True, 'node': self.identity(), 'ready': self.ready,
                    'leader': self.leader, 'peers': [self.identity()] + [dict(id=i, url=p['url'], boot=p.get('boot')) for i, p in self.peers.items()]})
            if kind == 'ELECTION':
                if sender['id'] < self.id:
                    self.event('ANSWER', f"Responded to node {sender['id']}; higher ID participates")
                return web.json_response({'ok': True, 'type': 'ANSWER', 'id': self.id})
            if kind == 'FORWARD':
                if self.leader != self.id:
                    raise RuntimeError('Not leader')
                return web.json_response({'ok': True, 'entry': await self.submit(m['op'])})
            if kind == 'PREPARE' and self.delay_once:
                delay = self.delay_once
                self.delay_once = 0
                self.event('DELAY INJECTED', f'PREPARE held for {delay}s. Stale sessions will be checked after the delay.')
                await asyncio.sleep(delay)
            async with self.lock:
                if self.offline():
                    raise RuntimeError('Node temporarily offline (simulation)')
                if kind == 'COORDINATOR':
                    if sender['id'] < max(self.members()):
                        raise RuntimeError('Higher-ID node is available')
                    self.leader = sender['id']; self.session = m['session']; self.view = m['view']
                    self.ready = False; self.role = 'recovering'
                    self.event('COORDINATOR', f'Leader {self.leader} announced')
                    return web.json_response({'ok': True, 'snapshot': self.store.snapshot()})
                if sender['id'] != self.leader or m.get('session') != self.session:
                    raise RuntimeError('Stale or unknown leadership session')
                if kind == 'SYNC':
                    before = len(self.store.entries)
                    self.store.install(m['entries'])
                    self.event('LOG SYNCHRONISED', f'{before} -> {len(self.store.entries)} stored entries; confirmed prefix preserved.')
                elif kind == 'PREPARE':
                    if self.drop_once:
                        self.drop_once = False
                        self.event('FAULT', 'Dropped one PREPARE for demonstration')
                        raise RuntimeError('Injected lost replication message')
                    entry = m['entry']; validate_op(entry)
                    self.store.append(entry)
                    self.event('PREPARE ACK', f"#{entry['seq']} durably stored; acknowledgement returned to leader {self.leader}.")
                elif kind == 'APPLY':
                    before = self.store.committed
                    self.store.commit(m['seq'])
                    self.ready = True; self.role = 'follower'
                    self.event('APPLY', f'Confirmed through #{self.store.committed}; browser state updated in sequence order.')
                    if before != self.store.committed:
                        await self.snapshot_clients()
                else:
                    raise ValueError('Unknown peer message')
                return web.json_response({'ok': True})
        except OSError as exc:
            if isinstance(exc, (ClientError, TimeoutError)):
                self.event('RPC FAILED', f'Forwarding interrupted: {exc}; client will retry.')
                return web.json_response({'ok': False, 'error': 'Forwarding interrupted; retry'}, status=503)
            self.storage_error(exc)
            return web.json_response({'ok': False, 'error': 'Storage failure; writes halted'}, status=503)
        except (ValueError, KeyError, TypeError) as exc:
            self.event('MESSAGE REJECTED', str(exc))
            return web.json_response({'ok': False, 'error': str(exc)}, status=400)
        except Exception as exc:
            self.event('RPC REJECTED', str(exc))
            return web.json_response({'ok': False, 'error': str(exc)}, status=503)

    async def websocket(self, request):
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=512 * 1024)
        await ws.prepare(request)
        async with self.lock:
            self.clients.add(ws)
            self.event('CLIENT CONNECTED', f'{request.remote}; sending {self.store.committed} confirmed operations.')
            await ws.send_json({'type': 'INIT', 'entries': self.store.entries[:self.store.committed]})
            await ws.send_json({'type': 'STATUS', **self.status()})
        try:
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue
                op = None
                try:
                    value = json.loads(msg.data)
                    if value.get('type') == 'OP':
                        op = value.get('op')
                        entry = await self.submit(op)
                        await ws.send_json({'type': 'COMMIT', 'entry': entry})
                except ValueError as exc:
                    await ws.send_json({'type': 'ERROR', 'retry': False, 'op_id': op.get('op_id') if isinstance(op, dict) else None, 'message': str(exc)})
                except Exception as exc:
                    await ws.send_json({'type': 'ERROR', 'retry': True, 'message': str(exc)})
        finally:
            self.clients.discard(ws)
            self.event('CLIENT DISCONNECTED', f'{request.remote}; {len(self.clients)} clients remain on this node.')
        return ws

    async def operation(self, request):
        try:
            return web.json_response({'entry': await self.submit(await request.json())})
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({'error': str(exc)}, status=503)

    async def fault(self, request):
        if not self.args.demo_controls or request.headers.get('X-CoDraw-Token') != self.args.token:
            raise web.HTTPForbidden()
        await self.control('drop')
        return web.json_response({'ok': True, 'message': 'Next PREPARE will be dropped'})

    async def control_handler(self, request):
        if not self.args.demo_controls or request.headers.get('X-CoDraw-Token') != self.args.token:
            raise web.HTTPForbidden()
        try:
            m = await request.json()
            # Hard exit is intentionally terminal-only; never expose it remotely.
            if m.get('command') not in {'status', 'peers', 'drop', 'delay', 'offline', 'online', 'election'}:
                raise ValueError('Unknown or disallowed command')
            await self.control(m['command'], m.get('seconds', 0))
            return web.json_response({'ok': True})
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)

    async def start(self, app):
        self.http = ClientSession(timeout=ClientTimeout(total=self.args.rpc_timeout))
        self.discovery = None; self.transport = None
        if not self.args.no_discovery:
            try:
                self.transport, self.discovery = await discovery.start(self)
            except OSError as exc:
                self.event('DISCOVERY WARNING', f'{exc}; use --seed if multicast is unavailable')
        self.event('LISTENING', f'Open {self.url} | TCP {self.args.port}, UDP {self.args.discovery_port} | cluster={self.args.cluster}')
        self.event('PERSISTENCE', f'Journal: {self.store.path}; terminal events: {Path(self.args.data_dir) / "terminal.log"}')
        if self.args.console:
            from terminal import start_console
            start_console(self)
        self.spawn(self.tick())

    async def stop(self, app):
        self.event('SHUTDOWN', 'Stopping this node. Peers detect missing heartbeats and recover; local logs retained.')
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        for ws in list(self.clients):
            await ws.close()
        if self.transport:
            self.transport.close()
        await self.http.close()

    def app(self):
        app = web.Application(client_max_size=16 * 1024 * 1024)
        async def index(r): return web.FileResponse(ROOT / 'index.html')
        async def status(r): return web.json_response(self.status())
        async def history(r): return web.json_response(self.store.snapshot())
        app.add_routes([web.get('/', index), web.get('/ws', self.websocket),
                        web.get('/api/status', status), web.get('/api/history', history),
                        web.post('/api/op', self.operation), web.post('/rpc', self.rpc_handler),
                        web.post('/api/demo/drop-next', self.fault),
                        web.post('/api/demo/control', self.control_handler)])
        app.on_startup.append(self.start); app.on_cleanup.append(self.stop)
        return app


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id', type=int, required=True)
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--advertise', default='127.0.0.1', help='LAN IPv4 address for multi-laptop use')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--data-dir', default=None)
    p.add_argument('--seed', action='append', default=[], help='Optional initial http://host:port; repeatable')
    p.add_argument('--cluster', default='codraw-group21')
    p.add_argument('--token', default='codraw-local-demo', help='Same shared peer token on every node')
    p.add_argument('--multicast', default='239.255.21.21')
    p.add_argument('--discovery-port', type=int, default=45454)
    p.add_argument('--interface', default='0.0.0.0', help='Local IPv4 multicast interface')
    p.add_argument('--no-discovery', action='store_true')
    p.add_argument('--min-nodes', type=int, default=2)
    p.add_argument('--heartbeat', type=float, default=.6)
    p.add_argument('--failure-timeout', type=float, default=3.0)
    p.add_argument('--rpc-timeout', type=float, default=1.5)
    p.add_argument('--settle', type=float, default=1.5)
    p.add_argument('--demo-controls', action='store_true')
    p.add_argument('--console', action='store_true', help='Interactive status/failure commands in this terminal')
    p.add_argument('--trace-heartbeats', action='store_true', help='Print every successful heartbeat as well as failures')
    args = p.parse_args()
    if args.id < 1 or args.min_nodes < 1:
        p.error('IDs and min-nodes must be positive')
    args.data_dir = args.data_dir or str(ROOT / 'data' / f'node-{args.id}')
    return args


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
    args = parse_args()
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)
    log_file = RotatingFileHandler(Path(args.data_dir) / 'terminal.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    log_file.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    logging.getLogger().addHandler(log_file)
    try:
        web.run_app(Node(args).app(), host=args.host, port=args.port, access_log=None)
    except (OSError, ValueError, KeyError) as exc:
        logging.error('STARTUP HALTED | %s | Preserve data files; verify address/port and journal integrity before restarting.', exc)
        raise SystemExit(2)
