from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _get_proxy_endpoint() -> tuple[str, int] | None:
    for env_var in ("BITGET_HTTP_PROXY", "BITGET_HTTPS_PROXY"):
        value = os.getenv(env_var)
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.hostname and parsed.port:
            return parsed.hostname, parsed.port
    return None


PROXY_ENDPOINT = _get_proxy_endpoint()


@pytest.mark.skipif(PROXY_ENDPOINT is None, reason="Proxy variables not configured")
def test_proxy_tcp_connectivity():
    host, port = PROXY_ENDPOINT  # type: ignore[misc]
    with socket.create_connection((host, port), timeout=5):
        pass
