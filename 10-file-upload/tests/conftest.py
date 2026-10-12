"""Test fixtures for the file upload service.

Each test gets its own temp storage directory and a fresh metadata store, so
tests are isolated and never touch the real ``storage/`` folder. The
process-global ``settings.storage_dir`` is repointed per-test.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from upload import config
from upload.main import app
from upload.models import _MetadataDB, set_metadata


@pytest.fixture
def storage_dir() -> Path:
    """A fresh, per-test temp directory used for file and metadata storage."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Repoint the global storage root so both routes and storage use it.
        config.settings.storage_dir = root
        set_metadata(_MetadataDB(root / "metadata.db"))
        yield root


@pytest.fixture
def client(storage_dir: Path) -> TestClient:
    """A FastAPI ``TestClient`` backed by the isolated temp storage."""
    with TestClient(app) as c:
        yield c