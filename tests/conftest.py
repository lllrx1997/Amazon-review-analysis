import os

import pytest

from ad_optimizer.config import Settings


@pytest.fixture(autouse=True)
def isolate_server_configuration(monkeypatch):
    """Never inherit developer API keys or scraper settings in isolated tests."""
    names = set(Settings.model_fields)
    for key in list(os.environ):
        if key.lower() in names:
            monkeypatch.delenv(key, raising=False)
