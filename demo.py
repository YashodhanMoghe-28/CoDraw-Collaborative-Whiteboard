"""Launch three local nodes. Ctrl+C stops all. No Docker or shell activation needed."""
import argparse
import subprocess
import sys
import time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--multicast-only',action='store_true');args=p.parse_args()
root=Path(__file__).resolve().parent
processes=[]
try:
    for i in (1,2,3):
        cmd=[sys.executable,str(root/'server.py'),'--id',str(i),'--port',str(8764+i),'--demo-controls']
        if not args.multicast_only:
            for j in (1,2,3):
                if i!=j:cmd+=['--seed',f'http://127.0.0.1:{8764+j}']
        processes.append(subprocess.Popen(cmd,cwd=root))
    print('\nOpen http://localhost:8765 in two browser tabs.\nNode ports: 1=8765, 2=8766, 3=8767. Ctrl+C stops all.\n',flush=True)
    while all(p.poll() is None for p in processes):time.sleep(1)
except KeyboardInterrupt:pass
finally:
    for p in processes:
        if p.poll() is None:p.terminate()
    for p in processes:
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();p.wait()
