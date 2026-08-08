#!/usr/bin/env bash
# 启动 MiniCPM-o 原生语音输出服务（文本 + 24 kHz WAV）。
set -euo pipefail

RUNTIME_VENV="${MINICPM_RUNTIME_VENV:-/opt/minicpm-service/venv}"
OMNI_BIN="${RUNTIME_VENV}/bin/vllm-omni"
MODEL_DIR="${MINICPM_OMNI_MODEL_DIR:-/mnt/d/AI/models/MiniCPM-o-4_5-AWQ}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_CONFIG="${MINICPM_OMNI_CONFIG:-${SCRIPT_DIR}/../config/minicpmo_4_5_awq_3090.yaml}"
CUDA_NVCC="$(find "${RUNTIME_VENV}/lib" -path '*/site-packages/nvidia/cu13/bin/nvcc' -print -quit)"

if [[ ! -x "${OMNI_BIN}" || ! -f "${MODEL_DIR}/config.json" || ! -f "${DEPLOY_CONFIG}" || ! -x "${CUDA_NVCC}" ]]; then
  echo "错误：复用环境中缺少 vLLM-Omni，或模型配置不完整。"
  echo "运行环境：${RUNTIME_VENV}"
  echo "模型目录：${MODEL_DIR}"
  exit 1
fi
if pgrep -f '/opt/minicpm-service/venv/bin/vllm serve' >/dev/null; then
  echo "错误：普通 MiniCPM vLLM（端口 8000）仍在运行。请先停止它，3090 单卡不能并行运行 Omni。"
  exit 1
fi

# vLLM 预热时需要 nvcc。直接使用复用虚拟环境自带的 CUDA Toolkit，
# 无需 source activate，也无需额外安装 /usr/local/cuda。
CUDA_HOME=${CUDA_HOME:-$(dirname "$(dirname "${CUDA_NVCC}")")}
CUDA_LINK_DIR="/tmp/minicpm-cuda-links-${UID}"
install -d -m 700 "${CUDA_LINK_DIR}"
ln -sfn "${CUDA_HOME}/lib/libcudart.so.13" "${CUDA_LINK_DIR}/libcudart.so"
ln -sfn /usr/lib/wsl/lib/libcuda.so.1 "${CUDA_LINK_DIR}/libcuda.so"

export CUDA_HOME
export PATH="${RUNTIME_VENV}/bin:${CUDA_HOME}/bin:${PATH}"
export LIBRARY_PATH="${CUDA_LINK_DIR}:${CUDA_HOME}/lib:/usr/lib/wsl/lib${LIBRARY_PATH:+:${LIBRARY_PATH}}"
export LD_LIBRARY_PATH="${CUDA_LINK_DIR}:${CUDA_HOME}/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "运行环境：${RUNTIME_VENV}"
echo "Omni 模型：${MODEL_DIR}"
echo "CUDA Toolkit：${CUDA_HOME}"

exec "${OMNI_BIN}" serve "${MODEL_DIR}" \
  --omni \
  --deploy-config "${DEPLOY_CONFIG}" \
  --trust-remote-code \
  --allowed-local-media-path /tmp \
  --host 0.0.0.0 \
  --port 8099
