#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
runtime_dir="$project_dir/.run"
pid_file="$runtime_dir/stripe-poc.pid"
listener_pid_file="$runtime_dir/stripe-listener.pid"
listener_log="$runtime_dir/stripe-listen.log"

mkdir -p "$runtime_dir"

if [[ -f "$pid_file" ]]; then
  pid="$(<"$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    printf '%s\n' "The service is already running (PID $pid). Run ./end.sh before restarting." >&2
    exit 1
  fi
  rm -f "$pid_file"
fi

if [[ -f "$listener_pid_file" ]]; then
  listener_pid="$(<"$listener_pid_file")"
  if [[ "$listener_pid" =~ ^[0-9]+$ ]] && kill -0 "$listener_pid" 2>/dev/null; then
    printf '%s\n' "The Stripe listener is already running (PID $listener_pid). Run ./end.sh before restarting." >&2
    exit 1
  fi
  rm -f "$listener_pid_file"
fi

if [[ ! -f .env ]]; then
  printf '%s\n' "Missing .env. Create it with: cp .env.example .env" >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' "Missing .venv. Create it with: python3 -m venv .venv && .venv/bin/python -m pip install -e ." >&2
  exit 1
fi

if ! command -v stripe >/dev/null; then
  printf '%s\n' "Stripe CLI is required. Install it with: npm install -g @stripe/cli" >&2
  exit 1
fi

set -a
# .env is this application's local configuration.
source .env
set +a

stripe listen --forward-to localhost:4242/webhook > "$listener_log" 2>&1 &
listener_pid=$!
printf '%s\n' "$listener_pid" > "$listener_pid_file"

cleanup() {
  if kill -0 "$listener_pid" 2>/dev/null; then
    kill "$listener_pid"
  fi
  rm -f "$pid_file" "$listener_pid_file"
}
trap cleanup EXIT INT TERM

for _ in {1..20}; do
  webhook_secret="$(grep -Eo 'whsec_[[:alnum:]_]+' "$listener_log" | head -n 1 || true)"
  if [[ -n "$webhook_secret" ]]; then
    break
  fi
  if ! kill -0 "$listener_pid" 2>/dev/null; then
    cat "$listener_log" >&2
    exit 1
  fi
  sleep 0.5
done

if [[ -z "${webhook_secret:-}" ]]; then
  printf '%s\n' "Stripe CLI did not provide a webhook signing secret. See $listener_log" >&2
  exit 1
fi

export STRIPE_WEBHOOK_SECRET="$webhook_secret"
.venv/bin/python "$project_dir/app.py" &
app_pid=$!
printf '%s\n' "$app_pid" > "$pid_file"
printf '%s\n' "Stripe listener started; logs: $listener_log"

wait "$app_pid"
