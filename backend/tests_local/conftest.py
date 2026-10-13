"""Local, offline test harness: in-memory MongoDB (mongomock-motor), no network, no live server.
Run:  cd backend && python -m pytest tests_local -q
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "gov_test")
os.environ.setdefault("EDGE_SIGNING_SECRET", "test-edge-secret")
os.environ.setdefault("MASKING_KEY", "test-mask-key")
os.environ.setdefault("BOOTSTRAP_ADMIN_TOKEN", "test-bootstrap-admin-token")
os.environ["EMERGENT_LLM_KEY"] = ""

import types  # noqa: E402

# emergentintegrations is an Emergent-hosted package that is not installable offline; stub it.
_ei = types.ModuleType("emergentintegrations")
_llm = types.ModuleType("emergentintegrations.llm")
_chat = types.ModuleType("emergentintegrations.llm.chat")
class _Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: self
for _n in ("LlmChat", "UserMessage", "TextDelta", "StreamDone"):
    setattr(_chat, _n, _Dummy)
sys.modules.update({"emergentintegrations": _ei, "emergentintegrations.llm": _llm, "emergentintegrations.llm.chat": _chat})

import mongomock_motor  # noqa: E402
import motor.motor_asyncio as _motor  # noqa: E402

_motor.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient


def make_client(demo: bool):
    os.environ["DEMO_MODE"] = "true" if demo else "false"
    for m in [m for m in list(sys.modules) if m in ("server", "database", "auth", "seed_data") or m.startswith("routers")]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app)


@pytest.fixture()
def client():
    with make_client(False) as c:
        yield c


@pytest.fixture()
def demo_client():
    with make_client(True) as c:
        yield c


ADMIN = {"Authorization": "Bearer test-bootstrap-admin-token"}
