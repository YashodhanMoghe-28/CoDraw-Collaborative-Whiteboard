# CoDraw 1.1 — Multi-device Collaborative Whiteboard

Distributed Systems · WS26 · Group 21

**Three or four separate devices? Read [START_HERE.md](START_HERE.md). Run `start_lan.bat` once on each laptop.**

The LAN launcher includes interactive terminal commands, detailed protocol logging,
automatic settings recall, and controlled failure demonstrations. Terminal logs are
saved independently under each node's data directory.

An extension of your original Python/Canvas whiteboard into a multi-server LAN
project. Each server is both an election participant and a replica. Each browser
is a drawing client. **A browser alone cannot take over as leader.**

## One-laptop quick demo on Windows

1. Extract the ZIP to a normal folder (do not run inside the ZIP).
2. Install Python **3.11 or newer** if needed.
3. Double-click **`setup_windows.bat`** once. It creates `.venv` and installs the dependency.
4. Double-click **`start_demo.bat`**. Leave this terminal running.
5. Open **http://localhost:8765** in two browser tabs. Allow a few seconds for discovery/election.
6. Draw, erase, change colours, or clear the board. Check the cluster panel.

No Docker, Node.js, SQLite, Tkinter, PowerShell activation, or external service is
needed to run the project. Internet is needed for the initial Python dependency
installation only. The browser loads no external fonts, scripts or assets.

Equivalent commands:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe demo.py
```

On Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python demo.py
```

Stop the demo with Ctrl+C. Logs persist in `data/node-1`, `data/node-2`, and
`data/node-3`, so restarting restores the board. To reset, stop **all** nodes and
remove their data folders together. Do not delete one running replica's files.

## Features

- Shared 1000 × 600 Canvas with mouse/touch drawing, colour, brush size, eraser and clear.
- Export the current visible canvas to PNG.
- Optimistic drawing: pending strokes appear faintly until confirmed.
- Unique operation IDs, duplicate suppression and retry after reconnect.
- Browser reconnects automatically to discovered server endpoints.
- Pending operations survive reload in the same tab via sessionStorage.
- Dynamic UDP multicast server discovery; optional seed addresses when Wi-Fi blocks multicast.
- Peer heartbeat probes and **Bully election**: highest available eligible ID coordinates.
- Sequencer-based ordered delivery: session IDs, global sequence numbers, acknowledgements,
  gap detection, retry/recovery and identical committed-history fingerprints.
- In-memory state backed by fsynced JSONL logs; no shared database.
- Paused writes during election/recovery; full history transfer for new/restarted replicas.
- Recovery preserves confirmed prefixes and reconciles unconfirmed tails.
- Cluster role, leader, online nodes, local client count, history fingerprint and event timeline.
- Optional one-message-drop injection and automated multi-process integration tests.

## Run on three laptops

All laptops run the **same server program** and share a trusted private LAN.
Use unique IDs, and replace the example addresses with each laptop's real IPv4
address from `ipconfig`. Run setup on every laptop first.

| Laptop | Command (Windows CMD) | Browser URL on that laptop |
|---|---|---|
| A | `start_node.bat 3 192.168.1.13 8765` | `http://localhost:8765` |
| B | `start_node.bat 2 192.168.1.12 8765` | `http://localhost:8765` |
| C | `start_node.bat 1 192.168.1.11 8765` | `http://localhost:8765` |

The wrapper supplies both `--advertise` and `--interface`. Allow inbound TCP 8765
and UDP 45454 on the **private** network profile. Campus/guest Wi-Fi can block
peer-to-peer or multicast traffic; use a private router/hotspot if necessary.

All nodes must use the same cluster name and peer token. For a custom token use
`server.py` directly and pass the same `--token` on every laptop. The token is a
basic peer guard, not a substitute for TLS or production authentication.

If discovery is blocked, add a seed on each joining node:

```powershell
.venv\Scripts\python.exe server.py --id 2 --port 8765 --advertise 192.168.1.12 --interface 192.168.1.12 --seed http://192.168.1.13:8765
```

Seeded nodes exchange known peer addresses, so a seed is not a permanent central
server. Addresses learned by a browser are used for failover without refreshing.
After a full page refresh, the original HTTP host must be reachable: open a surviving
node's URL if necessary. Pending state is scoped to the browser tab and origin.

## Controlled failure demo on one laptop

For independent stop/restart control, start these in **three terminals**, instead
of `demo.py`:

```powershell
.venv\Scripts\python.exe server.py --id 1 --port 8765 --seed http://127.0.0.1:8766 --seed http://127.0.0.1:8767 --demo-controls
.venv\Scripts\python.exe server.py --id 2 --port 8766 --seed http://127.0.0.1:8765 --seed http://127.0.0.1:8767 --demo-controls
.venv\Scripts\python.exe server.py --id 3 --port 8767 --seed http://127.0.0.1:8765 --seed http://127.0.0.1:8766 --demo-controls
```

1. Open http://localhost:8765 and http://localhost:8766 in separate windows.
2. Node 3 should become leader. Draw from both windows; compare committed counts.
3. Stop node 3 using Ctrl+C in its terminal. Updates pause while nodes 1 and 2 elect node 2.
4. Continue drawing. Restart node 3 with the same command and data folder.
5. Node 3 recovers missed history and becomes leader again (Bully's highest-ID rule).
6. Drop a replication message on a follower:
   `.venv\Scripts\python.exe fault.py http://localhost:8766`
7. Draw again. The operation remains pending briefly, recovery repairs the log,
   and retries do not duplicate it. Compare fingerprints after the cluster settles.
8. Add node 4 with `--id 4 --port 8768 --seed http://127.0.0.1:8765`.
   It joins, catches up and can become leader after membership stabilises.

For discovery **without any seeds**, run `python demo.py --multicast-only`.

## Tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary logs and ephemeral TCP ports, launch real processes, and
clean up their processes afterward. The multicast test needs local UDP multicast.
See `docs/TEST_REPORT.md` for what was verified in the build environment.

## Protocol and scope

Read **`docs/PROTOCOL.md`** before your presentation. This is a teaching prototype
for a connected, trusted LAN with bounded communication delays and stable periods
between membership changes. It is **not Raft**, and it does **not** claim Byzantine
or arbitrary network-partition tolerance. Minimum live nodes defaults to two.

Bully elects the coordinator; the separate replication protocol waits for all
members of the current view to durably record an operation before applying it.
A failed member stalls writes until detection, election/recovery and a new stable
view. This is deliberately more conservative than majority-only replication.

The final proposal should use this actual protocol instead of old references to
Raft, terms/votes or SQLite. Automatic new-node participation is allowed only after
stabilisation and recovery; it is not tied only to the previous leader failing.

## Files

| File | Responsibility |
|---|---|
| `server.py` | HTTP/WebSocket API, Bully election, heartbeats, replication, recovery |
| `discovery.py` | UDP multicast announcements and discovery |
| `log_store.py` | Durable JSONL records, deduplication, recovery snapshots |
| `index.html` | Canvas UI, pending queue, failover, cluster dashboard |
| `lan.py` / `start_lan.bat` | Guided one-server-per-device LAN setup |
| `terminal.py` | Live terminal status and failure commands |
| `check_lan.py` | Read-only multi-device connectivity check |
| `demo.py` | Start/stop three local processes |
| `fault.py` | Inject one missed PREPARE on a demo-enabled node |
| `tests/test_system.py` | Storage and multi-process integration tests |
| `tests/test_client.cjs` | JavaScript client logic test with simulated browser APIs |
| `docs/PROTOCOL.md` | Message flow, guarantees, assumptions and limitations |
| `docs/DEMO_CHECKLIST.md` | Presentation sequence and acceptance checks |

## Troubleshooting

- **Waiting for peers:** start at least two nodes. `--min-nodes 1` is available for
  UI-only experiments, but removes the two-live-node guard.
- **Nodes cannot find each other:** check firewall, LAN address, UDP interface,
  cluster name and token; use `--seed` if multicast is blocked.
- **ID CONFLICT:** use unique server IDs and independent data directories.
- **Recovery paused / conflicting histories:** do not erase a confirmed log to
  force progress. Preserve all logs for diagnosis. This can indicate an unsupported
  partition scenario, an ID collision or manual data modification.
- **Address already in use:** stop the previous process or choose another port.
- **Pending changes:** wait for two nodes and completed recovery. Pending strokes
  are previews, not yet confirmed data.
- **Connection after refreshing a dead server's page:** open a surviving server's
  URL. Already-open pages can switch endpoints automatically.
- **No package named aiohttp:** use the virtual environment interpreter shown above.

Team: Yashodhan Moghe, Shruti Kudale, Mayuresh Shendkar, Mrunal Murudkar.
