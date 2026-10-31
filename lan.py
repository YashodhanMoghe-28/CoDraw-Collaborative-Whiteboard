"""Start one CoDraw server on each of 3 or 4 laptops. No code edits needed."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'device.local.json'


def ipv4(text):
    value = ipaddress.IPv4Address(text)
    if value.is_unspecified or value.is_multicast:
        raise ValueError('Use this laptop\'s IPv4 address, not 0.0.0.0 or multicast')
    return str(value)


def seed_url(text):
    if not text.startswith('http://'):
        text = 'http://' + text
    u = urlparse(text)
    host = ipv4(u.hostname or '')
    port = u.port or 8765
    if not 1 <= port <= 65535 or u.path not in ('', '/') or u.username:
        raise ValueError('Seed must be an IPv4 address with optional :port')
    return f'http://{host}:{port}'


def suggest_ip():
    # UDP connect selects an interface; no packet is transmitted.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 80))
            value = s.getsockname()[0]
            if not value.startswith('127.'):
                return value
    except OSError:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if not item[4][0].startswith('127.'):
                return item[4][0]
    except OSError:
        pass
    return ''


def ask(label, default, convert):
    while True:
        try:
            raw = input(f'{label}' + (f' [{default}]' if default != '' else '') + ': ').strip()
            return convert(raw or str(default))
        except ValueError as exc:
            print('Please correct the value:', exc)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id', type=int)
    p.add_argument('--ip')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--seed', action='append', default=[])
    p.add_argument('--cluster', default='codraw-group21')
    p.add_argument('--token', default='codraw-local-demo')
    p.add_argument('--trace-heartbeats', action='store_true')
    a = p.parse_args()
    saved = {}
    if CONFIG.exists():
        try:
            saved = json.loads(CONFIG.read_text())
        except (ValueError, OSError):
            pass
    print('\nCoDraw LAN | Run ONE server on EACH laptop\nAll devices: same Wi-Fi/LAN, same cluster/token, unique IDs 1..4.\n')
    if a.id is None:
        a.id = ask('Unique server ID (1 to 4)', saved.get('id', ''), int)
    if not 1 <= a.id <= 4:
        p.error('Choose a different ID 1, 2, 3 or 4 for each device')
    if a.ip is None:
        print('Check the Wi-Fi/Ethernet IPv4 address using ipconfig. Avoid VPN adapter addresses.')
        a.ip = ask('THIS laptop IPv4', suggest_ip() or saved.get('ip', ''), ipv4)
    try:
        a.ip = ipv4(a.ip)
        if not 1 <= a.port <= 65535:
            raise ValueError('Port must be 1..65535')
        if not a.seed:
            raw = input('Other laptop IP(s), comma separated (recommended; blank = multicast only)'
                        + (f" [{','.join(saved.get('seeds', []))}]" if saved.get('seeds') else '') + ': ').strip()
            a.seed = [x.strip() for x in raw.split(',') if x.strip()] or saved.get('seeds', [])
        seeds = [seed_url(x) for x in a.seed]
        with socket.socket() as s:
            s.bind((a.ip, a.port))
    except (ValueError, OSError) as exc:
        p.error(f'{exc}. Verify this laptop IP and close an existing server on this port.')
    CONFIG.write_text(json.dumps({'id': a.id, 'ip': a.ip, 'seeds': seeds}, indent=2))
    cmd = [sys.executable, '-u', str(ROOT / 'server.py'), '--id', str(a.id),
           '--advertise', a.ip, '--interface', a.ip, '--port', str(a.port),
           '--cluster', a.cluster, '--token', a.token, '--console', '--demo-controls']
    for seed in seeds:
        cmd += ['--seed', seed]
    if a.trace_heartbeats:
        cmd += ['--trace-heartbeats']
    print(f'\nOpen http://localhost:{a.port} on THIS laptop, or http://{a.ip}:{a.port} from another device.\n'
          'Allow Python on the Private firewall profile (TCP server port + UDP 45454).\n'
          'Do not use start_demo.bat for a multi-device demonstration.\n', flush=True)
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            return 0
    except OSError as exc:
        print('Unable to start server:', exc)
        return 1


if __name__ == '__main__':
    try:sys.exit(main())
    except (EOFError, KeyboardInterrupt):print('\nCancelled.')
