"""Durable JSONL WAL: prepared entries and delivery markers; no database."""
import hashlib
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(entries):
    return hashlib.sha256(canonical(entries).encode()).hexdigest()


class LogStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries = []
        self.repaired_tail_bytes = 0
        self.committed = 0
        self.by_op_id = {}
        if self.path.exists():
            raw = self.path.read_bytes()
            # A torn final record was never acknowledged; retain only complete lines.
            if raw and not raw.endswith(b'\n'):
                good = raw[:raw.rfind(b'\n') + 1]
                self.repaired_tail_bytes = len(raw) - len(good)
                self.path.with_suffix('.torn').write_bytes(raw[len(good):])
                with self.path.open('wb') as f:
                    f.write(good); f.flush(); os.fsync(f.fileno())
                raw = good
            for line in raw.splitlines():
                record = json.loads(line)
                if record['type'] == 'ENTRY':
                    self._add(record['entry'])
                elif record['type'] == 'COMMIT':
                    n = record['seq']
                    if not self.committed <= n <= len(self.entries):
                        raise ValueError('Invalid commit marker')
                    self.committed = n
                else:
                    raise ValueError('Unknown WAL record')

    def _add(self, entry):
        if entry['seq'] != len(self.entries) + 1 or entry['op_id'] in self.by_op_id:
            raise ValueError('Non-contiguous or duplicate log entry')
        self.entries.append(entry)
        self.by_op_id[entry['op_id']] = entry

    def _write(self, record):
        with self.path.open('a', encoding='utf-8') as f:
            f.write(canonical(record) + '\n'); f.flush(); os.fsync(f.fileno())

    def append(self, entry):
        n = entry['seq']
        if n <= len(self.entries):
            if self.entries[n - 1] != entry:
                raise ValueError('Conflicting history; refusing overwrite')
            return
        if n != len(self.entries) + 1 or entry['op_id'] in self.by_op_id:
            raise ValueError('Missing log entry or duplicate ID')
        self._write({'type': 'ENTRY', 'entry': entry})
        self._add(entry)

    def commit(self, n):
        if not self.committed <= n <= len(self.entries):
            raise ValueError('Invalid commit index')
        if n > self.committed:
            self._write({'type': 'COMMIT', 'seq': n})
            self.committed = n

    def extend(self, entries):
        if entries[:len(self.entries)] != self.entries:
            raise ValueError('Recovery history is not a compatible extension')
        for entry in entries[len(self.entries):]:
            self.append(entry)

    def install(self, entries):
        """Replace only an unconfirmed suffix during coordinated recovery."""
        if entries[:self.committed] != self.entries[:self.committed]:
            raise ValueError('Recovery would overwrite confirmed history')
        if entries == self.entries:
            return
        ids = set()
        for n, entry in enumerate(entries, 1):
            if entry['seq'] != n or entry['op_id'] in ids:
                raise ValueError('Invalid recovery snapshot')
            ids.add(entry['op_id'])
        temp = self.path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as f:
            for entry in entries:
                f.write(canonical({'type': 'ENTRY', 'entry': entry}) + '\n')
            f.write(canonical({'type': 'COMMIT', 'seq': self.committed}) + '\n')
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, self.path)
        self.entries = list(entries)
        self.by_op_id = {e['op_id']: e for e in entries}

    def snapshot(self):
        # Full replay snapshot: intentionally no compaction in this teaching project.
        entries = list(self.entries)
        return {'entries': entries, 'committed': self.committed, 'hash': digest(entries)}
