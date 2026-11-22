#!/usr/bin/env bash
# Laptop side, one command: rent a GPU, start vLLM on it (scripts/vm/serve_vllm.sh), open the ssh
# tunnel to localhost:8000 and wait until vLLM answers. Inspect then reaches the server through
# VLLM_BASE_URL=http://localhost:8000/v1 from .env.
#
# Usage: bash scripts/laptop/gpu_up.sh [extra `ic-vast rent` options, e.g. --timer 3h --config h200]
# End the session: uv run ic-vast destroy   (records the rental, then destroys the instance)
# Close the tunnel only: pkill -f "[l]ocalhost:8000 bluedot-vast"
set -euo pipefail
cd "$(dirname "$0")/../.."

PORT=8000
TIMEOUT_S=900 # first start took 2 min 40 s (weights download + engine init), 26-11-21
CURRENT=scratch/vast_current_instance.json
REMOTE_LOGS=/root/bluedot/logs/remote

# ic-vast keeps the active instance in this file until `ic-vast destroy`. Renting again would
# overwrite it: the old session would never be recorded, and the instance might still be billing.
if [[ -e $CURRENT ]]; then
  echo "[gpu_up] $CURRENT exists, so an instance is still recorded as active:" >&2
  cat "$CURRENT" >&2
  echo >&2
  echo "[gpu_up] End it first with 'uv run ic-vast destroy', then run this again." >&2
  exit 1
fi

# A tunnel left over from an earlier session would point at the old instance.
# pkill exits 1 when nothing matched, which is fine; anything else is a real error.
pkill -f "[l]ocalhost:$PORT bluedot-vast" || [[ $? -eq 1 ]]

# Blocks until the instance is ready, writes the ssh alias bluedot-vast, then starts the
# script detached with its log in $REMOTE_LOGS.
uv run ic-vast rent --script scripts/vm/serve_vllm.sh "$@"

ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L "$PORT:localhost:$PORT" bluedot-vast
echo "[gpu_up] tunnel open: localhost:$PORT -> bluedot-vast:$PORT"

echo "[gpu_up] waiting for vLLM (up to ${TIMEOUT_S}s) ..."
deadline=$((SECONDS + TIMEOUT_S))
until curl -sf "localhost:$PORT/health" >/dev/null; do
  # ic-vast's wrapper writes this line when serve_vllm.sh ends; vLLM should never end on its own.
  if ssh bluedot-vast "grep -qs '\[ic-vast\] script exited' $REMOTE_LOGS/serve_vllm_*.log"; then
    echo "[gpu_up] serve_vllm.sh exited on the instance. End of its log:" >&2
    ssh bluedot-vast "tail -n 40 $REMOTE_LOGS/serve_vllm_*.log" >&2
    exit 1
  fi
  if ((SECONDS > deadline)); then
    echo "[gpu_up] no answer after ${TIMEOUT_S}s. End of the server log:" >&2
    ssh bluedot-vast "tail -n 40 $REMOTE_LOGS/serve_vllm_*.log" >&2
    exit 1
  fi
  sleep 10
done

echo "[gpu_up] vLLM is up after $((SECONDS / 60)) min $((SECONDS % 60)) s in total. Models:"
curl -s "localhost:$PORT/v1/models"
echo
