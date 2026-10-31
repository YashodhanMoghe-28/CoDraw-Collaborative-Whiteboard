import asyncio,json,socket,subprocess,sys,tempfile,unittest,uuid
from pathlib import Path
import aiohttp
from log_store import LogStore
ROOT=Path(__file__).resolve().parents[1]
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
class StorageTests(unittest.TestCase):
    def test_snapshot_preserves_confirmed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=LogStore(Path(tmp)/'wal.jsonl')
            a={'seq':1,'op_id':'a'};b={'seq':2,'op_id':'b'};c={'seq':2,'op_id':'c'}
            s.append(a);s.commit(1);s.append(b)
            s.install([a,c]);self.assertEqual(s.entries,[a,c])
            with self.assertRaises(ValueError):s.install([{'seq':1,'op_id':'wrong'}])
            self.assertEqual(LogStore(s.path).committed,1)
    def test_replay_duplicate_torn_tail_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'log.jsonl';s=LogStore(p)
            e={'seq':1,'op_id':'a','kind':'CLEAR'}
            s.append(e);s.append(e);s.commit(1)
            with p.open('ab') as f:f.write(b'{"torn"')
            s=LogStore(p);self.assertEqual(s.entries,[e]);self.assertEqual(s.committed,1)
            self.assertTrue(p.with_suffix('.torn').exists())
            with self.assertRaises(ValueError):s.append(e|{'kind':'STROKE'})
class ClusterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ports={i:port() for i in (1,2,3,4)};self.procs={};self.logs=[]
        self.http=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
        for i in (1,2,3):self.start(i)
        try:await self.ready([1,2,3],3)
        except BaseException:
            await self.asyncTearDown();raise
    def url(self,i):return f'http://127.0.0.1:{self.ports[i]}'
    def start(self,i):
        f=open(Path(self.tmp.name)/f'{i}.txt','a');self.logs.append(f)
        cmd=[sys.executable,str(ROOT/'server.py'),'--id',str(i),'--port',str(self.ports[i]),'--data-dir',str(Path(self.tmp.name)/str(i)),'--no-discovery','--demo-controls','--heartbeat','.2','--failure-timeout','1','--settle','.4','--rpc-timeout','.6']
        for j in (1,2,3):
            if j!=i:cmd+=['--seed',self.url(j)]
        self.procs[i]=subprocess.Popen(cmd,stdout=f,stderr=f,cwd=ROOT)
    async def status(self,i):
        async with self.http.get(self.url(i)+'/api/status') as r:return await r.json()
    async def ready(self,ids,leader):
        for _ in range(130):
            try:
                states=await asyncio.gather(*(self.status(i) for i in ids))
                if all(s['ready'] and s['leader']==leader for s in states):return
            except Exception:pass
            await asyncio.sleep(.15)
        self.fail('\n'.join(p.read_text()[-3500:] for p in Path(self.tmp.name).glob('*.txt')))
    def clear(self):return dict(op_id=uuid.uuid4().hex,client_id='test',kind='CLEAR',data=None)
    async def op(self,i,op):
        for _ in range(60):
            try:
                async with self.http.post(self.url(i)+'/api/op',json=op) as r:
                    data=await r.json()
                    if r.status==200:return data['entry']
                    if r.status==400:self.fail(str(data))
            except (aiohttp.ClientError,asyncio.TimeoutError):pass
            await asyncio.sleep(.2)
        self.fail('Operation did not confirm')
    async def equal(self,ids,n):
        for _ in range(60):
            s=await asyncio.gather(*(self.status(i) for i in ids))
            if len({x['hash'] for x in s})==1 and all(x['committed']==n for x in s):return
            await asyncio.sleep(.1)
        self.fail(str(s))
    async def test_full_lifecycle(self):
        op=self.clear();self.assertEqual((await self.op(1,op))['seq'],1);self.assertEqual((await self.op(2,op))['seq'],1)
        stroke=self.clear()|dict(kind='STROKE',data=dict(color='#2563eb',width=4,points=[[10,20],[30,40]]))
        await asyncio.gather(self.op(1,stroke),self.op(2,self.clear()));await self.equal([1,2,3],3)
        async with self.http.post(self.url(2)+'/api/demo/drop-next',headers={'X-CoDraw-Token':'codraw-local-demo'}) as r:self.assertEqual(r.status,200)
        await self.op(1,self.clear());await self.equal([1,2,3],4)
        self.procs[3].kill();self.procs[3].wait();await self.ready([1,2],2)
        # Emulate a locally persisted, never replicated entry at the crashed leader.
        old=LogStore(Path(self.tmp.name)/'3'/'operations.jsonl')
        old.append(self.clear()|{'seq':5,'session':'interrupted-session'})
        await self.op(1,self.clear());await self.equal([1,2],5)
        self.start(3);await self.ready([1,2,3],3);await self.equal([1,2,3],5)
        self.start(4);await self.ready([1,2,3,4],4);await self.equal([1,2,3,4],5)
        await self.op(2,self.clear());await self.equal([1,2,3,4],6)
        async with self.http.post(self.url(1)+'/api/op',json={'kind':'STROKE'}) as r:self.assertEqual(r.status,400)
        async with self.http.post(self.url(1)+'/rpc',json={}) as r:self.assertEqual(r.status,403)
        async with self.http.ws_connect(self.url(1)+'/ws') as ws:
            m=await ws.receive_json();self.assertEqual(m['type'],'INIT');self.assertEqual(len(m['entries']),6)
            m=await ws.receive_json();self.assertEqual(m['type'],'STATUS')
    async def asyncTearDown(self):
        for p in self.procs.values():
            if p.poll() is None:p.terminate()
        for p in self.procs.values():
            try:p.wait(timeout=4)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for f in self.logs:f.close()
        await self.http.close();self.tmp.cleanup()
class MulticastTests(ClusterTests):
    def start(self,i):
        f=open(Path(self.tmp.name)/f'{i}.txt','a');self.logs.append(f)
        cmd=[sys.executable,str(ROOT/'server.py'),'--id',str(i),'--port',str(self.ports[i]),
             '--data-dir',str(Path(self.tmp.name)/str(i)),'--cluster','test-'+Path(self.tmp.name).name,
             '--heartbeat','.2','--failure-timeout','1','--settle','.5','--interface','127.0.0.1']
        self.procs[i]=subprocess.Popen(cmd,stdout=f,stderr=f,cwd=ROOT)
    async def test_full_lifecycle(self):
        # No seeds: nodes must find each other via actual UDP multicast packets.
        await self.op(1,self.clear());await self.equal([1,2,3],1)
        self.procs[1].kill();self.procs[1].wait()
        await self.ready([2,3],3);await self.op(2,self.clear());await self.equal([2,3],2)
        self.procs[2].kill();self.procs[2].wait()
        for _ in range(30):
            if not (await self.status(3))['ready']:break
            await asyncio.sleep(.15)
        async with self.http.post(self.url(3)+'/api/op',json=self.clear()) as r:self.assertEqual(r.status,503)
class FourDeviceTests(ClusterTests):
    """Four distinct IP addresses, all on the SAME TCP port (device topology)."""
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();shared=port()
        self.ports={i:shared for i in (1,2,3,4)};self.procs={};self.logs=[]
        self.http=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
        for i in (1,2,3,4):self.start(i)
        try:await self.ready([1,2,3,4],4)
        except BaseException:
            await self.asyncTearDown();raise

    def url(self,i):return f'http://127.0.0.{i}:{self.ports[i]}'

    def start(self,i):
        f=open(Path(self.tmp.name)/f'{i}.txt','a');self.logs.append(f)
        cmd=[sys.executable,str(ROOT/'server.py'),'--id',str(i),
             '--host',f'127.0.0.{i}','--advertise',f'127.0.0.{i}',
             '--port',str(self.ports[i]),'--data-dir',str(Path(self.tmp.name)/str(i)),
             '--no-discovery','--demo-controls','--heartbeat','.2',
             '--failure-timeout','1','--settle','.5','--rpc-timeout','.6']
        for j in (1,2,3,4):
            if i!=j:cmd+=['--seed',self.url(j)]
        self.procs[i]=subprocess.Popen(cmd,stdout=f,stderr=f,cwd=ROOT)

    async def control(self,i,command,seconds=0):
        async with self.http.post(self.url(i)+'/api/demo/control',
            headers={'X-CoDraw-Token':'codraw-local-demo'},
            json={'command':command,'seconds':seconds}) as r:
            self.assertEqual(r.status,200,await r.text())

    async def test_full_lifecycle(self):
        await self.op(1,self.clear());await self.equal([1,2,3,4],1)
        # A slow follower causes a bounded RPC timeout, then log repair.
        await self.control(2,'delay',2)
        await self.op(1,self.clear());await self.equal([1,2,3,4],2)
        # Isolate only the current leader; surviving three elect ID 3.
        await self.control(4,'offline',20)
        await self.ready([1,2,3],3)
        await self.op(2,self.clear());await self.equal([1,2,3],3)
        await self.control(4,'online')
        await self.ready([1,2,3,4],4);await self.equal([1,2,3,4],3)
        # A follower process can fail; the remaining view continues after recovery.
        self.procs[2].kill();self.procs[2].wait()
        await asyncio.sleep(1.5)
        await self.ready([1,3,4],4)
        await self.op(1,self.clear());await self.equal([1,3,4],4)
        self.start(2);await self.ready([1,2,3,4],4);await self.equal([1,2,3,4],4)
        # Validate explanatory terminal events, not just final state.
        logs='\n'.join(p.read_text() for p in Path(self.tmp.name).glob('*.txt'))
        for label in ['ELECTION START','SEND ELECTION','REPLY PREPARE',
                      'DELAY INJECTED','RPC FAILED','COUNTERMEASURE',
                      'LEADER SUSPECTED','PEER RETURNED','LOG SYNCHRONISED','READY']:
            self.assertIn(label,logs)

class FailureGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_disk_write_failure_blocks_confirmation(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from server import Node
        with tempfile.TemporaryDirectory() as tmp:
            n=Node(SimpleNamespace(id=1,port=8765,advertise='127.0.0.1',data_dir=tmp,seed=[],failure_timeout=3))
            n.ready=True;n.leader=1;n.view=[1];n.session='test'
            op=dict(op_id='disk-test',client_id='test',kind='CLEAR',data=None)
            with patch.object(n.store,'append',side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):await n.submit(op)
            self.assertTrue(n.storage_failed);self.assertFalse(n.ready)
            self.assertEqual(n.store.committed,0)
            self.assertEqual(n.events[-1]['kind'],'STORAGE ERROR')

class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_and_hard_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'server.py'),
                '--id','1','--port',str(port()),'--data-dir',tmp,'--no-discovery','--console',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
            try:
                output,_=await asyncio.wait_for(p.communicate(b'status\npeers\ndrop\ndelay 2\noffline 3\nonline\ncrash\n'),10)
                self.assertEqual(p.returncode,77)
                text=output.decode()
                for label in ['STATUS','PEER','FAULT ARMED','NETWORK SIMULATION','NETWORK RESTORED','CRASH SIMULATION']:
                    self.assertIn(label,text)
                self.assertTrue((Path(tmp)/'terminal.log').exists())
            finally:
                if p.returncode is None:p.kill();await p.wait()

class LauncherTests(unittest.TestCase):
    def test_seed_validation(self):
        from lan import seed_url,ipv4
        self.assertEqual(seed_url('192.168.1.11'),'http://192.168.1.11:8765')
        self.assertEqual(seed_url('192.168.1.11:9000'),'http://192.168.1.11:9000')
        for bad in ['https://example.com','127.0.0.1:99999','garbage']:
            with self.assertRaises(ValueError):seed_url(bad)
        with self.assertRaises(ValueError):ipv4('0.0.0.0')

if __name__=='__main__':unittest.main()
