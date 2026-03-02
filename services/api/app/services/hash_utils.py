from __future__ import annotations
import hashlib
import json
from typing import Any, Mapping

def stable_json_dumps(obj: Any) -> str:
    # canonical JSON for stable hashing
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def json_hash(obj: Any) -> str:
    s = stable_json_dumps(obj)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
