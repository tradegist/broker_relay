"""E2E test — verify REMOTE_CLIENT_ENABLED=false stops the remote-client container."""

import subprocess
import time

import httpx
import pytest

REMOTE_CLIENT_URL = "http://localhost:15010/health"
E2E_COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.test.yml",
    "-p", "ibkr-relay-test",
    "--env-file", ".env.test",
]


def _remote_client_is_reachable(timeout: float = 2.0) -> bool:
    try:
        resp = httpx.get(REMOTE_CLIENT_URL, timeout=timeout)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _wait_for_remote_client(up: bool, *, retries: int = 10, delay: float = 2.0) -> None:
    """Wait for remote-client to become reachable (up=True) or unreachable (up=False)."""
    for _ in range(retries):
        if _remote_client_is_reachable() == up:
            return
        time.sleep(delay)
    state = "reachable" if up else "unreachable"
    pytest.fail(f"remote-client did not become {state} after {retries * delay}s")


class TestRemoteClientEnabled:
    """Scale remote-client to 0, verify it stops, scale back, verify it recovers."""

    def test_remote_client_disable_and_reenable(self) -> None:
        # Precondition: remote-client is running (conftest preflight check guarantees this)
        assert _remote_client_is_reachable(), "remote-client should be reachable before test"

        # Scale remote-client to 0
        subprocess.run(
            [*E2E_COMPOSE, "up", "-d", "--scale", "remote-client=0", "--no-recreate"],
            check=True,
            capture_output=True,
        )
        _wait_for_remote_client(up=False)

        # Scale remote-client back to 1
        subprocess.run(
            [*E2E_COMPOSE, "up", "-d", "--scale", "remote-client=1", "--no-recreate"],
            check=True,
            capture_output=True,
        )
        _wait_for_remote_client(up=True, retries=20)
