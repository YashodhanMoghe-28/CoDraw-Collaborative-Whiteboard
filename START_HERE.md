# CoDraw 1.1 — Three or four devices

**Copy/extract this complete project onto EVERY laptop. Run one Python server per
laptop. Do not use start_demo.bat for the multi-device demonstration.**

## Windows setup

1. Connect all laptops to the same private Wi-Fi or wired network.
2. Run `setup_windows.bat` once on each laptop (requires installed Python 3.11+).
3. Double-click `start_lan.bat` on each laptop.
4. Enter a unique ID, confirm **that laptop's own IPv4 address**, and enter another
   laptop's address as a seed. Use `ipconfig` to find the Wi-Fi/Ethernet IPv4 address.
   The suggested address may be a VPN adapter: verify it.
5. Allow Python on the **Private** firewall profile when Windows asks.
6. Open **http://localhost:8765** in a browser on each laptop. Leave every terminal open.

Example addresses ONLY — replace them with your actual addresses:

| Device | Unique ID | Its own IPv4 | Seed (another device) |
|---|---:|---|---|
| Laptop A | 1 | 192.168.1.11 | 192.168.1.12 |
| Laptop B | 2 | 192.168.1.12 | 192.168.1.11 |
| Laptop C | 3 | 192.168.1.13 | 192.168.1.11 |
| Optional laptop D | 4 | 192.168.1.14 | 192.168.1.11 |

All devices can use port **8765**, because their IPs differ. Only multiple instances
on the *same* laptop need different ports. With three devices ID 3 normally leads;
with four, ID 4 normally leads. Two live nodes are required by default.

Each device saves its own settings in `device.local.json`. The launcher asks you to
confirm them on the next start. It does not save your token. Default cluster and
peer token match across the supplied launchers; use the same custom values everywhere
if you override them.

### Direct commands instead of the wizard

Run ONE corresponding command on EACH device, in the extracted project folder:

```bat
start_node.bat 1 192.168.1.11 8765 192.168.1.12
start_node.bat 2 192.168.1.12 8765 192.168.1.11
start_node.bat 3 192.168.1.13 8765 192.168.1.11
```

Optional fourth device:

```bat
start_node.bat 4 192.168.1.14 8765 192.168.1.11
```

Linux/macOS equivalent after installing requirements in a venv:

```bash
.venv/bin/python lan.py --id 1 --ip 192.168.1.11 --seed 192.168.1.12
```

For every successful heartbeat to be printed, add `--trace-heartbeats` when running
`lan.py` or `server.py`. Normal mode prints failed probes, peer returns, a periodic
health summary, and all election/replication/recovery steps.

## Terminal commands

Type into the running server terminal and press Enter. Incoming log lines may
appear while you type; your command is still accepted.

| Command | What happens | What the terminal explains |
|---|---|---|
| `status` | Read current local state | Role, leader, membership, stored/confirmed indexes |
| `peers` | List discovered devices | ID, network endpoint and online/offline state |
| `drop` | Reject the next PREPARE on this follower | Failed acknowledgement -> pause -> recover -> client retry |
| `delay 5` | Delay the next PREPARE by 5 seconds | Timeout -> repair; old-session message is rejected if it arrives later |
| `offline 12` | Disable this node's peer communication and writes for 12 seconds | Missing heartbeat -> election on survivors -> recovery on return |
| `online` | End a simulated outage immediately | Re-probe and synchronise before accepting new work |
| `election` | Request a fresh election | ELECTION -> ANSWER -> COORDINATOR -> log synchronisation |
| `crash` | Immediately terminate this server process | Other terminals detect loss and recover; restart this launcher to rejoin |
| `help` | Show commands | Command summary |
| Ctrl+C | Stop this server normally | Retains all local data; peers use heartbeat failure detection |

`offline` is a controlled application-level outage, not an OS firewall change.
It blocks new writes on the isolated node. Other terminals continue to show the
actual detection and recovery protocol. General arbitrary partitions remain outside
this protocol's guarantees.

## Suggested demonstration

1. Start A, B and C. Run `peers` on each and show ID 3 as leader.
2. Draw on A while clearing/drawing on B. Read SEND PREPARE, PREPARE ACK, SEND APPLY,
   APPLY and COMMIT. Compare confirmed counts/fingerprints on all browser panels.
3. On follower A, type `drop`. Draw on B. Watch the missed acknowledgement and
   COUNTERMEASURE messages. The client's retry must not create a duplicate entry.
4. On follower B, type `delay 5`; draw again. Show the timeout and repair.
5. On the leader C, type `crash`. B becomes leader after detection and recovery.
   Draw while C is down. Restart C with the same data directory. Its history catches up.
6. On leader C, type `offline 12`. Explain the same failover path, then the return.
7. Start D with ID 4. Show discovery, a new stable view, recovery, then highest-ID takeover.
8. Type `status` and `peers`. Compare fingerprints again.

Do one fault at a time and wait for READY before the next. Every server writes a
rotating terminal transcript to `data/node-ID/terminal.log` (plus up to 3 backups).
These are actual events, not canned messages. `docs/TERMINAL_EXAMPLE.txt` is only an
illustrative reading guide.

## If devices cannot connect

From the project folder:

```bat
.venv\Scripts\python.exe check_lan.py 192.168.1.11 192.168.1.12 192.168.1.13
```

Check the printed URLs/IDs and fingerprints. If a check fails:

- Ensure the server is running and the advertised address belongs to that laptop.
- All devices must be on the same reachable LAN; guest/campus Wi-Fi may isolate clients.
- Allow inbound TCP **8765** and UDP **45454** on the Private profile.
- Enter another device as a seed if multicast is blocked. Seeds are bootstrap addresses,
  not permanent leaders. Known peer addresses are exchanged between servers.
- Use the same cluster name and token, and unique IDs. ID collisions pause a node.
- Disable VPN routing for the demo or explicitly choose the LAN interface.

If needed, these commands can be run manually in an **Administrator CMD** to create
Private-profile, local-subnet-only firewall rules (replace 8765 if using another port):

```bat
netsh advfirewall firewall add rule name="CoDraw TCP" dir=in action=allow protocol=TCP localport=8765 profile=private remoteip=localsubnet
netsh advfirewall firewall add rule name="CoDraw UDP discovery" dir=in action=allow protocol=UDP localport=45454 profile=private remoteip=localsubnet
```

## Failure boundaries

Implemented handling includes leader/follower process loss, single-node simulated
network interruption, delayed/rejected replication, duplicate retries, rejoining,
torn final log records, and disk-write failure guards. A failed disk blocks further
acknowledgements until you fix storage and restart; the code never deletes a confirmed
prefix to force progress.

This is still a trusted-LAN teaching prototype, not Byzantine or arbitrary partition
consensus. In particular, a **four-node 2+2 network split is not safely supported** by
Bully election plus a minimum of two live nodes. Do not claim that in your report.
Physical laptop/Wi-Fi/firewall behaviour must be checked on your network.
