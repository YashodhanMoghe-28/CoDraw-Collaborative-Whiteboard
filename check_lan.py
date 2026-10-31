"""Read-only HTTP reachability check: python check_lan.py IP1 IP2 IP3"""
import argparse
import json
import urllib.request
import urllib.error
from lan import seed_url
p=argparse.ArgumentParser(description=__doc__);p.add_argument('addresses',nargs='+');a=p.parse_args()
for address in a.addresses:
    try:
        url=seed_url(address)
        with urllib.request.urlopen(url+'/api/status',timeout=4) as response:s=json.load(response)
        print(f"OK {url} | node={s['node_id']} leader={s['leader']} role={s['role']} ready={s['ready']} confirmed={s['committed']}")
        print('   history fingerprint:',s['hash'])
    except (ValueError,OSError,urllib.error.URLError) as exc:
        print(f'FAIL {address}: {exc}')
        print('   Check server terminal, IP, firewall TCP port, shared LAN and Wi-Fi client isolation.')
