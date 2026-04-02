#!/usr/bin/env bash
# Helper: detect and validate poller configuration.
# Source this after loading .env. Sets COMPOSE_PROFILES if poller-2 is configured.

# Validate that all required env vars for a poller are set.
# Usage: _validate_poller_env ""    (poller 1 — vars without suffix)
#        _validate_poller_env "_2"  (poller 2 — vars with _2 suffix)
# Returns 0 if all vars are set, 1 if none are set.
# Exits with error if partially configured.
_validate_poller_env() {
  local suffix="${1:-}"
  local required=(IBKR_FLEX_TOKEN IBKR_FLEX_QUERY_ID TARGET_WEBHOOK_URL WEBHOOK_SECRET)
  local missing=() set_count=0

  for var in "${required[@]}"; do
    local full="${var}${suffix}"
    if [[ -z "${!full:-}" ]]; then
      missing+=("$full")
    else
      ((set_count++)) || true
    fi
  done

  # None set — not configured (OK)
  if [[ $set_count -eq 0 ]]; then
    return 1
  fi

  # Some set, some missing — partial config error
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: Poller${suffix:- } partially configured. Missing: ${missing[*]}" >&2
    exit 1
  fi

  return 0
}

_validate_poller2() {
  if _validate_poller_env "_2"; then
    export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}poller2"
  fi
}

_validate_poller2
