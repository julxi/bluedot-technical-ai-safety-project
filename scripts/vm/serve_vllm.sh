#!/usr/bin/env bash
# Start a vLLM server for Olmo 3 on a rented GPU. Inspect on the laptop reaches it through an
# ssh tunnel: ssh -N -L 8000:localhost:8000 bluedot-vast
# Usage (on the instance, from /root/bluedot):
#   bash scripts/vm/serve_vllm.sh [model] [revision] [reasoning parser] [max model length]
# From the laptop: bash scripts/laptop/gpu_up.sh --script_args "<model> <revision> [parser] [len]"
# Example judge: --script_args "microsoft/phi-4 main none 16384" (Phi-4's context is 16,384).
#
# The served model name is derived from what is served, e.g. allenai/Olmo-3-7B-Think-SFT at main
# (commit 0123abc...) -> olmo-3-7b-think-sft.main.0123abc. Inspect records it as the model of
# every run (openai-api/vllm/<name>), so each log names the checkpoint and its exact weights.
# Intentionally not passed by hand: a hand-typed name can disagree with what is served.
set -euo pipefail

# vLLM and its Python packages live in this venv in the vastai/vllm image.
source /venv/main/bin/activate

MODEL="${1:-allenai/Olmo-3-7B-Think}"
REVISION="${2:-main}"
# olmo3 splits Olmo 3's thinking from its answer. Judge models need their own parser, or "none".
REASONING_PARSER="${3:-olmo3}"
# Context length (prompt + reply). 32,768 for Olmo 3 Think (its model card's recommendation);
# models with a shorter context need their own, as vLLM refuses a length above the model's.
MAX_MODEL_LEN="${4:-32768}"

# Branch names move; the commit hash records which weights were served.
SHA=$(python3 -c "import sys; from huggingface_hub import HfApi; print(HfApi().model_info(sys.argv[1], revision=sys.argv[2]).sha)" "$MODEL" "$REVISION")
SERVED_NAME="$(basename "$MODEL" | tr '[:upper:]' '[:lower:]').${REVISION}.${SHA:0:7}"
echo "[serve_vllm] $(date -Is) model=$MODEL revision=$REVISION sha=$SHA served_name=$SERVED_NAME reasoning_parser=$REASONING_PARSER max_model_len=$MAX_MODEL_LEN vllm=$(vllm --version)"
nvidia-smi --query-gpu=name,memory.total,power.limit --format=csv

PARSER_ARGS=()
if [[ "$REASONING_PARSER" != "none" ]]; then
  PARSER_ARGS=(--reasoning-parser "$REASONING_PARSER")
fi

exec vllm serve "$MODEL" \
  --revision "$SHA" \
  --served-model-name "$SERVED_NAME" \
  --host 127.0.0.1 --port 8000 \
  --dtype bfloat16 \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization 0.90 \
  --seed 0 \
  "${PARSER_ARGS[@]}"