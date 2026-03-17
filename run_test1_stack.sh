#!/bin/zsh
set -e

cd /Users/db/Desktop/Ai

# Start lokale DOM adapter op de achtergrond
./venv/bin/python dom_adapter.py > /tmp/dom_adapter_test1.log 2>&1 &
ADAPTER_PID=$!

cleanup() {
  if kill -0 "$ADAPTER_PID" >/dev/null 2>&1; then
    kill "$ADAPTER_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

# Wacht kort tot adapter luistert
sleep 2

# Start Streamlit app op de voorgrond
./venv/bin/python -m streamlit run test1.py
