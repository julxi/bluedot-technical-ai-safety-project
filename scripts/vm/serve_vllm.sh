#!/usr/bin/env bash
# Start a vLLM server for Olmo 3 on a rented GPU. Inspect on the laptop reaches it through an
# ssh tunnel: ssh -N -L 8000:localhost:8000 bluedot-vast
# Usage (on the instance, from /root/bluedot): bash scripts/vm/serve_vllm.sh [model] [revision]
set -euo pipefail

# vLLM and its Python packages live in this venv in the vastai/vllm image.
source /venv/main/bin/activate

MODEL="${1:-allenai/Olmo-3-7B-Think}"
REVISION="${2:-main}"

# Branch names move; the commit hash records which weights were served.
SHA=$(python3 -c "import sys; from huggingface_hub import HfApi; print(HfApi().model_info(sys.argv[1], revision=sys.argv[2]).sha)" "$MODEL" "$REVISION")
echo "[serve_vllm] $(date -Is) model=$MODEL revision=$REVISION sha=$SHA vllm=$(vllm --version)"
nvidia-smi --query-gpu=name,memory.total,power.limit --format=csv

exec vllm serve "$MODEL" \
  --revision "$SHA" \
  --served-model-name olmo \
  --host 127.0.0.1 --port 8000 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --seed 0 \
  --reasoning-parser olmo3