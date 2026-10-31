# CoDraw 1.1 — Multi-device demonstration update

- Guided LAN launcher for 3 or 4 devices, own-IP validation, optional seed peers,
  independent local settings and a connectivity diagnostic.
- Interactive terminal commands: status, peers, drop, delay, offline, online,
  election and hard crash. Fault controls are explicit; crash is terminal-only.
- Detailed send/receive/acknowledgement, membership, failure suspicion, election,
  duplicate suppression, storage and recovery events with rotating log files.
- Peer cluster-name validation; clearer duplicate-ID and disk-write failure guards.
- Four distinct-address/same-port integration test, latency/network-outage scenarios
  and explanatory-log assertions. Physical Windows/LAN validation remains necessary.

# CoDraw 1.0 — Distributed implementation

The uploaded starter had one WebSocket server, a Canvas client and a simple JSONL
store. This version retains that application model and replaces the single-server
backend with discovery, election, replication and recovery.

- Serve the UI and WebSocket endpoint from the same Python HTTP port.
- Replace the websockets dependency with aiohttp for both HTTP peer RPC and WebSockets.
- Add UDP discovery, optional seeds, transitive peer information and heartbeat probes.
- Add Bully election and per-leadership-session fencing checks.
- Add all-view PREPARE/APPLY replication and recovery of stored/confirmed prefixes.
- Add durable JSONL delivery markers and snapshot installation without a database.
- Add client failover, pending-operation persistence, PNG export and status dashboard.
- Add independent Windows node launchers, local demo runner, fault injector and tests.

The protocol is scoped explicitly to the course's local-network crash demonstration.
It does not implement Raft, Byzantine agreement or arbitrary partition tolerance.
