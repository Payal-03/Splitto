"""Shared pytest fixtures for test isolation."""

import copy
import pytest
from backend import storage

_INITIAL_TRIPS = copy.deepcopy(storage.trips)


@pytest.fixture(autouse=True)
def reset_in_memory_trips():
    """Restore in-memory trip store from a fresh copy of seeds before every test."""
    storage.trips.clear()
    storage.trips.update(copy.deepcopy(_INITIAL_TRIPS))
