
import json
import os


class LogStore:
    def __init__(self, path):
        self.path = path
        self.entries = []
        self.by_op_id = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return

        with open(self.path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not line:
                    continue

                entry = json.loads(line)

                self.entries.append(entry)
                self.by_op_id[entry["op_id"]] = entry

    def last_seq(self):
        return self.entries[-1]["seq"] if self.entries else 0

    def append(self, op):
        existing = self.by_op_id.get(op["op_id"])

        if existing:
            return existing, False

        entry = {
            "seq": self.last_seq() + 1,
            "epoch": 1,
            "op_id": op["op_id"],
            "kind": op["kind"],
            "data": op.get("data"),
            "client_id": op.get("client_id"),
        }

        with open(self.path, "a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")
            file.flush()
            os.fsync(file.fileno())

        self.entries.append(entry)
        self.by_op_id[entry["op_id"]] = entry

        return entry, True
