"""Test fixtures. A fresh SQLite database is created and seeded once per test session.

Environment variables are set BEFORE the app is imported so settings/engine pick them up.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="phishguard-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    "ENVIRONMENT": "test",
    "AI_PROVIDER": "demo",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "CHROMA_PATH": str(_tmp / "chroma"),
    "RATE_LIMIT_AUTH": "1000",
    "RATE_LIMIT_AI": "1000",
    "RATE_LIMIT_REPORT": "1000",
    "JWT_SECRET": "test-secret-0123456789abcdef0123456789abcdef",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.cache import cache  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402
from app.seed import run as seed_run  # noqa: E402

GLOBEX = "globex.example.com"
INITECH = "initech.example.com"


@pytest.fixture(scope="session", autouse=True)
def _database():
    Base.metadata.create_all(engine)
    seed_run(reset=True)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset_state():
    limiter.reset()
    cache.clear()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


class Session:
    """A logged-in TestClient that automatically sends the CSRF header."""

    def __init__(self, client: TestClient, csrf: str, user: dict):
        self.client, self.csrf, self.user = client, csrf, user

    def _h(self, kw):
        kw.setdefault("headers", {})["X-CSRF-Token"] = self.csrf
        return kw

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, **kw):
        return self.client.post(url, **self._h(kw))

    def patch(self, url, **kw):
        return self.client.patch(url, **self._h(kw))

    def delete(self, url, **kw):
        return self.client.delete(url, **self._h(kw))


def login(email: str, password: str = DEMO_PASSWORD) -> Session:
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return Session(client, r.json()["csrf_token"], r.json()["user"])


@pytest.fixture
def anon():
    return TestClient(app)


@pytest.fixture
def admin():
    return login(f"admin@{GLOBEX}")


@pytest.fixture
def manager():
    return login(f"manager@{GLOBEX}")


@pytest.fixture
def learner():
    return login(f"learner@{GLOBEX}")


@pytest.fixture
def super_admin():
    return login(f"superadmin@{GLOBEX}")


@pytest.fixture
def other_admin():
    """Admin of the OTHER tenant (Initech)."""
    return login(f"admin@{INITECH}")
