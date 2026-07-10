import json
import os
import threading
from config import PERSIST


_snapshot = {}
_snapshot_lock = threading.Lock()


# 保存快照
def save_snapshot(section, data):
    with _snapshot_lock:
        _snapshot[section] = data
        _write_file()

# 返回快照
def load_snapshot():
    global _snapshot
    path = PERSIST["snapshot_path"]
    with _snapshot_lock:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _snapshot = json.load(f)
            return _snapshot
        return {}


def get_snapshot_section(section):
    return _snapshot.get(section)


def _write_file():
    path = PERSIST["snapshot_path"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_snapshot, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp_path, path)
