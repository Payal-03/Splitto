"""Shared pytest fixtures for test isolation."""

import pytest
from backend import storage


@pytest.fixture(autouse=True)
def isolated_test_db(tmp_path):
    """Initialize a fresh temporary SQLite database before every test."""
    storage.init_db(tmp_path / "test_splitto.db")
