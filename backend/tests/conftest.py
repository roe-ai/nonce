import os
import tempfile

from cryptography.fernet import Fernet

_tmp = tempfile.mkdtemp()
os.environ.update(
    TURSO_DATABASE_URL="",
    SIGNALS_URL="",
    SIGNALS_DETECTOR="",
    NTFY_TOPIC="",
    LOCAL_DB_PATH=os.path.join(_tmp, "test.db"),
    NONCE_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NONCE_ADMIN_TOKEN="test-admin",
    QUIET_HOURS="[0, 0]",
    SMS_ENABLED="true",
    TWILIO_ACCOUNT_SID="",
    TWILIO_AUTH_TOKEN="",
    PRODUCTION="false",
    OPENAI_API_KEY="",
    AZURE_OPENAI_API_KEY="",
    AZURE_OPENAI_ENDPOINT="",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
    GOOGLE_CLIENT_ID="test-client.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="test-secret",
    DASHBOARD_URL="http://localhost:3000",
    PUBLIC_URL="http://localhost:8000",
    OLD_PUBLIC_URLS="[]",
)

import pytest  # noqa: E402

from nonce import broker, db  # noqa: E402
from fake_gmail import FakeGmail  # noqa: E402


class FakeDetector:
    """Scripted detector: tests set the next signals."""

    def __init__(self) -> None:
        self.access_signals: dict = {}
        self.search_signals: dict = {}
        self.content_signals: dict = {}
        self.last_access_state: dict = {}

    async def access(self, state):
        self.last_access_state = state
        return self.access_signals or None

    async def search(self, state):
        return self.search_signals or None

    async def content(self, state):
        return self.content_signals or None


TEST_USER = "user-test"
SAFE_ACCESS = {"user_initiated": 0.95, "consistent": 0.9, "scope_fits": 0.9, "crawl": 0.2, "category": "travel"}
SAFE_SEARCH = {"serves": 0.9, "crawl": 0.1, "category": "travel"}


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    await db.migrate()
    await db.insert("users", {"id": TEST_USER, "google_sub": "test", "email": "test@example.com", "created_at": db.now()})
    for provider in ("gmail", "calendar", "drive", "slack"):
        await db.insert(
            "connections",
            {"user_id": TEST_USER, "provider": provider, "mode": "google", "account": "test@example.com", "status": "active", "created_at": db.now()},
        )
    broker.use_provider(FakeGmail())


@pytest.fixture
def detector():
    fake = FakeDetector()
    fake.access_signals = dict(SAFE_ACCESS)
    fake.search_signals = dict(SAFE_SEARCH)
    fake.content_signals = {"injection": 0.01}
    broker.use_detector(fake)
    return fake


@pytest.fixture
async def agent():
    row, _ = await broker.create_agent(TEST_USER, f"agent-{db.new_id()[:6]}")
    return row
