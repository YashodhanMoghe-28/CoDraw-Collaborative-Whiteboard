
import argparse
import asyncio
import json
import logging

import websockets
from websockets.exceptions import ConnectionClosed

from log_store import LogStore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("codraw")

VALID_KINDS = {"STROKE", "CLEAR"}


class Server:
    def __init__(self, log_path):
        self.store = LogStore(log_path)
        self.clients = set()

        # Serialize client registration and operation commits.
        self.lock = asyncio.Lock()

    async def send(self, ws, message):
        try:
            await ws.send(json.dumps(message))
            return True
        except ConnectionClosed:
            return False

    async def broadcast(self, message):
        """Broadcast one message to every connected client."""
        clients = list(self.clients)

        if not clients:
            return

        results = await asyncio.gather(
            *(self.send(client, message) for client in clients)
        )

        for client, success in zip(clients, results):
            if not success:
                self.clients.discard(client)

    async def broadcast_status(self):
        await self.broadcast({
            "type": "STATUS",
            "clients": len(self.clients),
            "committed": self.store.last_seq()
        })

    async def handle_op(self, ws, op):
        if (
            not isinstance(op, dict)
            or op.get("kind") not in VALID_KINDS
            or not isinstance(op.get("op_id"), str)
            or not op["op_id"]
        ):
            await self.send(ws, {
                "type": "ERROR",
                "message": "Invalid operation"
            })
            return

        # Keep appending and broadcasting in the same order.
        async with self.lock:
            entry, is_new = self.store.append(op)

            if is_new:
                log.info(
                    "COMMIT seq=%s kind=%s op_id=%s",
                    entry["seq"],
                    entry["kind"],
                    entry["op_id"]
                )

                await self.broadcast({
                    "type": "COMMIT",
                    "entry": entry
                })
            else:
                # A retry must not create a second operation.
                await self.send(ws, {
                    "type": "COMMIT",
                    "entry": entry
                })

    async def handler(self, ws):
        # Register the client and send its initial history atomically
        # relative to operation commits.
        async with self.lock:
            self.clients.add(ws)

            await self.send(ws, {
                "type": "INIT",
                "entries": self.store.entries
            })

        log.info(
            "Client connected. Active clients: %d",
            len(self.clients)
        )

        await self.broadcast_status()

        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await self.send(ws, {
                        "type": "ERROR",
                        "message": "Invalid JSON"
                    })
                    continue

                if not isinstance(message, dict):
                    continue

                if message.get("type") == "OP":
                    await self.handle_op(ws, message.get("op"))

        except ConnectionClosed:
            pass

        finally:
            async with self.lock:
                self.clients.discard(ws)

            log.info(
                "Client disconnected. Active clients: %d",
                len(self.clients)
            )

            await self.broadcast_status()


async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", default="board.jsonl")

    args = parser.parse_args()

    server = Server(args.log)

    log.info(
        "Loaded %d operations from %s",
        len(server.store.entries),
        args.log
    )

    async with websockets.serve(
        server.handler,
        args.host,
        args.port
    ):
        log.info(
            "Server listening on ws://%s:%d",
            args.host,
            args.port
        )

        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Server stopped")
