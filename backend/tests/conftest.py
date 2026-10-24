import os
import tempfile

# Tests never call a real model and never write to the project audit log.
os.environ["ECOMETRIC_PROVIDER"] = "rules"
os.environ["GEMINI_API_KEY"] = ""
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"
os.environ["ECOMETRIC_AUDIT_PATH"] = os.path.join(tempfile.mkdtemp(), "audit.jsonl")

import pytest  # noqa: E402

from app.data.store import store  # noqa: E402


@pytest.fixture
def elec():
    return store.load_sample("campus_electricity")


@pytest.fixture
def air():
    return store.load_sample("air_quality")


@pytest.fixture
def waste():
    return store.load_sample("waste_collection")
