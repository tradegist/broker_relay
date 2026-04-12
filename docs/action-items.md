# Action Items — Code Quality & Resilience

Priority-ordered list of improvements identified during the April 2026 architecture audit.

---

## 1. Add health checks to production docker-compose

**Priority:** High
**Why:** The production `docker-compose.yml` has `restart: always` on all services but no health checks. This means Docker only restarts a container if the process exits. A hung Python process (blocked on I/O, deadlocked asyncio loop, stuck HTTP handler) will stay alive forever without serving traffic. Health checks already exist in `docker-compose.test.yml` — they just need to be ported.

**Files to change:**
- `docker-compose.yml`

**Task:**
Add a `healthcheck` block to both the `relays` and `debug` services in `docker-compose.yml`. Use the same approach as `docker-compose.test.yml` (Python `urllib.request.urlopen` against the `/health` endpoint), but with production-appropriate intervals:

```yaml
# For relays service (port 8000)
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s

# For debug service (port 9000)
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

Do NOT change the test or local compose files — they already have their own health check configs.

---

## 2. Restart listener task on crash

**Priority:** High
**Why:** In `services/relay_core/main.py`, the `_run_listener()` function (lines 65-74) is launched once via `asyncio.create_task()` at line 118. If the listener's internal `while True` loop exits — either from a `FatalListenerError` or an unforeseen exception that escapes `_listen()` — the task completes and is never restarted. The pollers survive (they each have their own `while True`), but the WebSocket listener silently dies. Docker's `restart: always` doesn't help because the process itself is still running (pollers and HTTP server are fine).

**Files to change:**
- `services/relay_core/main.py`

**Task:**
Wrap the body of `_run_listener()` in a `while True` loop with a sleep-before-retry. The function currently looks like this (lines 65-74):

```python
async def _run_listener(relay: BrokerRelay) -> None:
    if relay.listener_config is None:
        return
    try:
        await start_listener(relay_name=relay.name)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("[%s] Listener crashed — pollers continue", relay.name)
```

Change it so the listener is retried after a delay when it crashes. `asyncio.CancelledError` must still propagate (it means the service is shutting down). `FatalListenerError` is already handled inside `_listen()` (it logs and returns cleanly), so it will surface here as a normal return — the retry loop handles that too.

Use a fixed 30-second delay before restart. Log clearly that a restart is happening so it's visible in `make logs`. The early return for `listener_config is None` must remain outside the loop.

**Existing test file:** `services/relay_core/test_listener_engine.py`
Add a test that verifies: when `start_listener` raises an exception, `_run_listener` calls it again (i.e., retries). Mock `start_listener` to raise on first call and succeed (or be cancelled) on second call. Also test that `CancelledError` is not retried.

---

## 3. Add WebSocket reconnection tests

**Priority:** Medium
**Why:** The reconnection logic in `services/relay_core/listener_engine.py` (lines 349-437) is the most complex async code in the project. It handles exponential backoff (5s → 10s → 20s → ... → 300s cap), fatal vs. transient errors, debounce buffer flushing on disconnect, and backoff reset on successful connection. None of this is tested. The unit tests in `test_listener_engine.py` only cover event dispatch and dedup — not the connection lifecycle.

**Files to change:**
- `services/relay_core/test_listener_engine.py`

**Task:**
Add tests for the `_listen()` function in `listener_engine.py`. The function is private but can be tested by importing it directly or by testing through the public `start_listener()` entry point. You will need to mock:

- `aiohttp.ClientSession` and the WebSocket it returns
- The relay's `ListenerConfig.connect` callback
- `asyncio.sleep` (to avoid real delays and to assert backoff values)

Test these scenarios:

1. **Successful connection then server closes**: mock WS to yield a CLOSE message. Assert the function reconnects (loops back) with `INITIAL_RETRY_DELAY` (5s).

2. **Exponential backoff**: mock WS to fail on connect (raise `aiohttp.ClientError`) three times in a row. Assert sleep is called with 5, 10, 20 seconds.

3. **Backoff reset on success**: after two failures (backoff reaches 10s), mock a successful connection that then closes. Assert the next retry delay resets to 5s.

4. **Fatal error stops retrying**: mock the `connect` callback to raise `FatalListenerError`. Assert the function returns (does not loop).

5. **Debounce buffer flushed on disconnect**: configure a non-zero `debounce_ms`, mock a connection that closes. Assert `DebounceBuffer.flush()` is called before the reconnect sleep.

The reconnection constants are defined at module level (lines 101-104): `INITIAL_RETRY_DELAY = 5`, `MAX_RETRY_DELAY = 300`, `RETRY_BACKOFF_FACTOR = 2`. Reference these in assertions rather than hardcoding values.

---

## 4. Add memory limits to production docker-compose

**Priority:** Low
**Why:** No resource limits are set on any container. On a small droplet (1-2 GB RAM), a runaway process (e.g., a broker API returning an unexpectedly large response that gets loaded into memory) could OOM the host and take down all services including Caddy. This is unlikely but easy to guard against.

**Files to change:**
- `docker-compose.yml`

**Task:**
Add `mem_limit` to each service in `docker-compose.yml`. Suggested values for a 2 GB droplet:

- `caddy`: `128m`
- `relays`: `512m`
- `debug`: `128m`

Example:
```yaml
relays:
  mem_limit: 512m
```

These are soft guidelines — adjust based on actual droplet size. The goal is to prevent one container from consuming all host memory. Do NOT add CPU limits (unnecessary at this scale) and do NOT change the test or local compose files.
