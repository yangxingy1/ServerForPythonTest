import json
import os
from config import PERSIST


_snapshot = {}

# 保存快照
def save_snapshot(section, data):
    _snapshot[section] = data
    _write_file()

# 返回快照
def load_snapshot():
    global _snapshot
    path = PERSIST["snapshot_path"]
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_snapshot, f, ensure_ascii=False, indent=2)
