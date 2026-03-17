#!/bin/zsh
set -e

cd /Users/db/Desktop/Ai

./venv/bin/python dom_adapter.py > /tmp/dom_adapter_live.log 2>&1 &
ADAPTER_PID=$!

./venv/bin/python push_dom_snapshots.py --interval 15 > /tmp/dom_pusher_live.log 2>&1 &
PUSHER_PID=$!

cleanup() {
  if kill -0 "$PUSHER_PID" >/dev/null 2>&1; then
    kill "$PUSHER_PID" >/dev/null 2>&1 || true
  fi
  if kill -0 "$ADAPTER_PID" >/dev/null 2>&1; then
    kill "$ADAPTER_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

sleep 3

./venv/bin/python -m streamlit run test1.py
