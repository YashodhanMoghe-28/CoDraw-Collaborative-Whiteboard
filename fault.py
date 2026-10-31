"""Remote demo controls; node must have --demo-controls. Hard crash is terminal-only."""
import argparse,json,urllib.request
p=argparse.ArgumentParser();p.add_argument('url');p.add_argument('--token',default='codraw-local-demo')
p.add_argument('--command',choices=['drop','delay','offline','online','status','peers','election'],default='drop')
p.add_argument('--seconds',type=float,default=10);a=p.parse_args()
r=urllib.request.Request(a.url.rstrip('/')+'/api/demo/control',
    data=json.dumps({'command':a.command,'seconds':a.seconds}).encode(),
    headers={'X-CoDraw-Token':a.token,'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(r,timeout=5) as response:print(json.loads(response.read()))
