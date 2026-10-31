# Five-minute demonstration

1. **Architecture:** point out three independent Python servers and browser clients.
   Each server has its own JSONL file. Explain that a leader is a role, not a special machine.
2. **Discovery:** start two nodes, then a third. Show the membership panel and highest-ID leader.
3. **Concurrent drawing:** open two browser windows against different nodes. Draw overlapping
   colours, then clear while drawing from the other window. Both replay one ordered history.
4. **Reliable delivery:** run fault.py on a follower. Draw once. Show the FAULT and recovery
   events and verify the pending count returns to zero without a duplicated operation.
5. **Leader crash:** stop the highest-ID server. Show the pause, Bully election and new leader.
   Draw again after recovery. Compare /api/status hashes from the remaining replicas.
6. **Rejoin:** restart the stopped server. Show its missing operations recovered and its
   higher-ID takeover. Every replica should have the same committed count and fingerprint.
7. **Persistence:** stop all servers; start them again using the same folders. The board returns.

Record these measurements yourself on the actual classroom network:

| Measurement | Your observed result |
|---|---|
| Time from leader stop to writes resuming | |
| Number of operations before/after failover | |
| Fingerprints equal on every live replica | |
| Lost-message retry produced exactly one operation | |
| Restarted node recovered all confirmed strokes | |

Explain the limits honestly: LAN crash-recovery prototype, no Byzantine or partition
consensus guarantee, full-log snapshots, no production authentication. Election and
reliable replication are different parts of the implementation.
