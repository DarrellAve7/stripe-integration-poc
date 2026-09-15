#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pid_file="$project_dir/.run/stripe-poc.pid"
listener_pid_file="$project_dir/.run/stripe-listener.pid"

stop_app() {
  local pid

  if [[ ! -f "$pid_file" ]]; then
    return
  fi

  pid="$(<"$pid_file")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "Invalid app PID file; refusing to stop a process." >&2
    exit 1
  fi

  if kill -0 "$pid" 2>/dev/null; then
    local process_dir process_command
    process_dir="$(readlink -f "/proc/$pid/cwd")"
    process_command="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
    if [[ "$process_dir" != "$project_dir" || "$process_command" != *"$project_dir/app.py"* ]]; then
      printf '%s\n' "PID $pid is not this project's app process; refusing to stop it." >&2
      exit 1
    fi
    kill "$pid"
    printf '%s\n' "Stopped the Stripe POC service (PID $pid)."
  fi

  rm -f "$pid_file"
}

stop_listener() {
  local pid process_command

  if [[ ! -f "$listener_pid_file" ]]; then
    return
  fi

  pid="$(<"$listener_pid_file")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "Invalid listener PID file; refusing to stop a process." >&2
    exit 1
  fi

  if kill -0 "$pid" 2>/dev/null; then
    process_command="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
    if [[ "$process_command" != *"stripe listen --forward-to localhost:4242/webhook"* ]]; then
      printf '%s\n' "PID $pid is not this project's Stripe listener; refusing to stop it." >&2
      exit 1
    fi
    kill "$pid"
    printf '%s\n' "Stopped the Stripe listener (PID $pid)."
  fi

  rm -f "$listener_pid_file"
}

if [[ ! -f "$pid_file" && ! -f "$listener_pid_file" ]]; then
  printf '%s\n' "No processes are running through start.sh."
  exit 0
fi

stop_app
stop_listener
