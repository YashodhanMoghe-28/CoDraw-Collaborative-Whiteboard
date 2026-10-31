# CoDraw protocol and correctness boundary

## Model

Each Python process has a unique numerical ID, independent local data directory,
and HTTP endpoint. Browsers connect using WebSockets. HTTP peer RPCs carry discovery
probes, election, replication and recovery messages. UDP multicast is **only** for
host discovery; reliable ordered multicast is implemented at application level.

The intended environment is one trusted, connected LAN with bounded delays,
eventually accurate crash detection, and stable periods between failures/joins.
Demonstrate one failure at a time, allowing recovery to finish. In-memory membership
is refreshed by successful HTTP HELLO probes, not trusted solely from UDP packets.

Default timers: heartbeat 0.6 s, failure timeout 3 s, membership settling 1.5 s,
RPC timeout 1.5 s. They are demonstration parameters, not universal network bounds.

## Bully election

1. Every node independently probes peers. A missing leader or changed live set
   pauses writes and triggers election after the settling period.
2. Lower-ID nodes send ELECTION to higher-ID peers; receivers return ANSWER.
3. The highest observed live node also probes all known higher IDs. If none answer,
   it creates a new UUID leadership session and sends COORDINATOR to the view.
4. A recipient rejects a coordinator below a higher currently live ID.
5. The leader is usable only after log recovery completes.

A returning higher-ID node may take over. There is no majority voting, persisted
Raft term, or Raft log-election rule. The session UUID rejects messages from an old
coordinator session, but by itself is not a globally agreed fencing token.

## Stable-view operation path

1. Client sends OP with `op_id`, `client_id`, `kind`, `data`. Followers forward it.
2. The leader serialises requests with an asyncio lock and validates data.
3. It assigns a globally contiguous sequence number and leadership session.
4. The leader appends an ENTRY to its JSONL WAL and fsyncs it.
5. PREPARE sends the entry to **every other member of the current live view**.
   Each recipient checks the session, sequence and duplicate ID and durably appends
   before acknowledging. A gap or conflicting entry is rejected.
6. Only after all PREPARE acknowledgements, APPLY is sent to the view. Recipients
   persist a COMMIT marker and deliver the prefix to browsers in sequence order.
7. After all APPLY responses, the leader persists its COMMIT marker, broadcasts
   COMMIT, and confirms the original request. Browser acknowledgements are not required.

If an RPC fails, the leader stops accepting writes and enters recovery. Client
operations remain pending and are retried with the same ID. Retries of an already
confirmed operation return its original entry, without reapplying it. Reusing an ID
with different content is rejected.

Follower-to-browser updates use a full committed INIT replay to avoid ordering gaps;
leader clients usually receive incremental COMMIT. Full-history replay is simple but
not suitable for very large boards. The browser detects incremental sequence gaps
and reconnects for history. There is no separate unbounded out-of-order buffer:
server gaps trigger snapshot recovery, and client gaps trigger replay.

## Recovery and new nodes

COORDINATOR pauses each replica and obtains its complete stored log and local commit
index. Choose the snapshot with the greatest committed index, breaking ties by log
length. Verify that **every survivor's committed prefix** agrees with that history.
Refuse recovery if confirmed histories conflict.

Install the selected snapshot on all members. Only unconfirmed tails may be replaced;
confirmed prefixes cannot be overwritten. Install uses an fsynced temporary file
followed by atomic replacement. After all copies acknowledge, APPLY completes the
selected history before the leader resumes accepting new requests.

An unconfirmed operation can be completed during recovery even if its original
client never received an acknowledgement. An unconfirmed conflicting tail may be
replaced and must be retried by the client. This is why clients reuse operation IDs.
There is no guarantee that an unconfirmed request was rejected merely because a
connection failed.

The snapshot is the **full operation history**, not a raster image or compacted log.
New nodes join discovery immediately; the changed live set pauses and restabilises
before a new coordinator session recovers the complete view. All live servers then
participate. There is no separate permanent learner/voter configuration.

## Persistence

`operations.jsonl` contains ENTRY and COMMIT records, not just visible strokes.
Each acknowledged record is flushed and fsynced. On restart an incomplete final
line is copied into `.torn` and removed. Invalid complete records cause startup to
fail visibly rather than silently lose confirmed content. Process-crash recovery is
tested; power-loss durability across all operating systems/filesystems is not.

## What the implementation does and does not guarantee

Under the stated connected-LAN, accurate-failure-detection and stable-view model,
confirmed operations are copied to every member before client confirmation and
surviving replicas recover the same delivered prefix. Runtime fingerprints and
integration tests check convergence. This is not a formal consensus proof.

**Network partitions are unsupported.** The two-live-node minimum is only an
availability guard, not a quorum over a fixed voting configuration. Two separated
subgroups may independently form views and leaders. A session UUID or a high server
ID does not solve split brain. No guarantee is made for conflicting writes during
partitions, simultaneous loss of all copies, Byzantine processes, or disk corruption.
Conflicting confirmed histories stop recovery instead of silently merging drawings.

Peer RPCs require a shared token. Browser APIs are intentionally open to LAN users;
there are no user accounts, access control, TLS, encryption or rate limiting. Do not
expose the service to the public Internet. Maximum browser message is 512 KiB; a
stroke is capped at 6,000 points. Peer request limit is 16 MiB. Logs are not compacted;
reset/archive all nodes together between long demo sessions. Large history scaling,
partial-range transfer and incremental disk snapshots are future work.

## Useful endpoints

- `GET /` — browser interface.
- `GET /ws` — WebSocket client stream.
- `GET /api/status` — local role, membership, delivered hash and timeline.
- `GET /api/history` — stored entries (including an unconfirmed tail), commit index and hash.
- `POST /api/op` — same operation schema as OP; useful for tests.
- `POST /rpc` — peer protocol; requires X-CoDraw-Token.
- `POST /api/demo/drop-next` — drop next PREPARE; requires token and --demo-controls.

Library documentation: https://docs.aiohttp.org/en/stable/web_quickstart.html


## Version 1.1 observability and failure controls

`start_lan.bat` starts one server with an interactive terminal. Every phase logs the
local node ID, event kind and countermeasure. Successful heartbeats are summarised
periodically unless `--trace-heartbeats` is enabled. Failed probes log immediately;
failure suspicion occurs only after the configured timeout. Do not confuse suspicion
with proof of a crash.

`offline N` disables local peer RPCs and writes, while retaining local status/control
access. It is a controlled single-node interruption. `delay N` delays one PREPARE;
the session is rechecked after the delay. `drop` rejects one PREPARE. `crash` exits
without graceful shutdown and is only accepted from the terminal. HTTP controls
require both --demo-controls and the peer token; no remote crash endpoint exists.

Storage OSErrors halt acknowledgements on that node. Restart after fixing disk access;
auto-repair of arbitrary corruption is intentionally not attempted. Events are saved
in terminal.log with size-based rotation. A bootstrap cluster name is checked on every
peer RPC, in addition to the shared token. This does not provide production security.
