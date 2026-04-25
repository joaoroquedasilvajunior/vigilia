"""
In-memory session store for Farol conversation history.
Keyed by session_id (UUID string). Stores the last MAX_TURNS exchanges.
No Redis dependency for Phase 1 — survives restarts is not a requirement.
"""
import uuid
from collections import OrderedDict
from threading import Lock

MAX_SESSIONS = 500
MAX_TURNS = 4  # last 4 user+assistant pairs = 8 messages in context

_store: OrderedDict[str, list[dict]] = OrderedDict()
_lock = Lock()


def new_session() -> str:
    sid = str(uuid.uuid4())
    with _lock:
        _store[sid] = []
    return sid


def get_history(session_id: str) -> list[dict]:
    with _lock:
        return list(_store.get(session_id, []))


def append_turn(session_id: str, user_msg: str, assistant_msg: str) -> None:
    with _lock:
        if session_id not in _store:
            _store[session_id] = []
        history = _store[session_id]
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})
        # Keep only the last MAX_TURNS exchanges
        if len(history) > MAX_TURNS * 2:
            _store[session_id] = history[-(MAX_TURNS * 2):]
        # Evict oldest sessions if over cap
        if len(_store) > MAX_SESSIONS:
            _store.popitem(last=False)
