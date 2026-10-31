"""Daemon input thread keeps terminal commands usable on Windows and Unix."""
import asyncio
import threading

HELP = '''
================ CoDraw terminal commands ================
  status           Show local role, leader and confirmed index
  peers            List discovered devices and addresses
  drop             Drop next replication message (use on follower)
  delay 5          Delay next replication message by five seconds
  offline 12       Simulate this node losing peer connectivity
  online           End the simulated outage immediately
  election         Request another election using normal Bully rules
  crash            Hard-exit THIS server; restart to show recovery
  help             Show commands again
  Ctrl+C           Stop this server normally; retain its data
==========================================================
Type a command and press Enter. Logs continue while you type.
'''


def start_console(node):
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    print(HELP, flush=True)

    def reader():
        while True:
            try:
                line = input()
                if loop.is_closed():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, line)
            except (EOFError, OSError, RuntimeError):
                break

    async def consume():
        while True:
            parts = (await queue.get()).strip().lower().split()
            if not parts:
                continue
            if parts[0] == 'help':
                print(HELP, flush=True)
                continue
            try:
                seconds = float(parts[1]) if len(parts) > 1 else 10
                await node.control(parts[0], seconds)
            except Exception as exc:
                node.event('COMMAND ERROR', str(exc))

    threading.Thread(target=reader, daemon=True, name='codraw-console').start()
    node.spawn(consume())
