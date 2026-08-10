#!/usr/bin/env bash
# Install Qwen3-ASR into an isolated package layer without modifying MiniCPM.
set -euo pipefail

base_python="/opt/minicpm-service/venv/bin/python"
asr_venv="/mnt/d/AI/venvs/qwen3-asr"
model_dir="/mnt/d/AI/models/Qwen3-ASR-0.6B"

if [[ ! -x "${base_python}" ]]; then
  echo "MiniCPM base Python not found: ${base_python}" >&2
  exit 1
fi

if [[ ! -x "${asr_venv}/bin/python" ]]; then
  mkdir -p "$(dirname -- "${asr_venv}")"
  "${base_python}" -m venv --system-site-packages "${asr_venv}"
fi

"${asr_venv}/bin/python" -m pip install --upgrade \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  "qwen-asr==0.0.6" \
  "modelscope" \
  "coverage==7.15.4"

if [[ ! -f "${model_dir}/config.json" ]]; then
  mkdir -p "${model_dir}"
  "${asr_venv}/bin/modelscope" download \
    --model Qwen/Qwen3-ASR-0.6B \
    --local_dir "${model_dir}"
fi

"${asr_venv}/bin/python" -c \
  'import qwen_asr, torch, transformers; print("Qwen3-ASR ready", torch.__version__, transformers.__version__)'
