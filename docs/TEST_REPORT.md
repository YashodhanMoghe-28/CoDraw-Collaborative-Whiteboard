# Verification report

Build date: 31 October 2026.
Environment: Linux container, Python 3.12, aiohttp 3.14.4, Node.js 24.

## Executed successfully

`python -m unittest discover -s tests -v`

Eight test methods passed, including these real multi-process scenarios:

- Three servers discover seeded peers, settle and elect highest ID 3.
- Submit through followers and confirm the same operation once after duplicate retry.
- Concurrent STROKE and CLEAR requests produce matching histories.
- Intentionally dropped PREPARE is recovered; retry adds no duplicate.
- Hard-kill leader 3; nodes 1 and 2 elect 2 and accept another operation.
- Restart 3 with an explicitly injected unconfirmed conflicting tail; preserve
  confirmed survivor history and repair the returning log.
- Late node 4 joins, recovers existing history, becomes leader and handles updates.
- Initial WebSocket history and status messages are verified.
- Reject malformed operations and peer requests without the shared token.
- Independent no-seed cluster uses actual UDP multicast on the loopback interface.
- Follower failure is recovered; losing all but one node pauses writes by default.
- JSONL replay, duplicate entries, torn-tail repair, atomic snapshot replacement
  and refusal to overwrite a confirmed prefix.

Additional version 1.1 checks passed:

- Four processes use different loopback IP addresses on the same TCP port, simulating four devices.
- Delayed replication times out and recovers; a simulated leader outage elects a replacement.
- Returning higher-ID leader synchronises before resuming, and a restarted follower catches up.
- Expected election, replication, timeout, recovery and ready events appear in terminal logs.
- Disk-write failure blocks acknowledgement and confirmation.
- Interactive terminal commands work; hard-crash exits with code 77 and preserves the terminal log.
- Launcher validates device IPs and seed addresses.

`node tests/test_client.cjs`

Passed: pointer stroke input, confirmation, duplicate delivery, clear, switching
to a discovered endpoint, retrying the original operation ID, snapshot replay and
pending-queue persistence. This executes the actual HTML script with mocked DOM,
Canvas and WebSocket APIs. It does not validate visual rendering or browser network
policies.

`python -m compileall -q .`

Python source compilation passed.

## Not verified here

- Actual Windows execution or three physical laptops and their firewall/router rules.
- Browser visual rendering, real touch hardware or PNG download interaction.
  A Playwright Chromium download was attempted but the environment returned an
  invalid archive. JavaScript logic was tested separately as described above.
- Multicast through a physical LAN adapter. The environment has no default multicast
  interface; the automated multicast test explicitly uses 127.0.0.1.
- Byzantine faults, arbitrary partitions, power outages, high load or large histories.

Follow DEMO_CHECKLIST.md on the classroom network before presentation. These tests
are evidence for the documented scenarios, not a proof of consensus correctness.
