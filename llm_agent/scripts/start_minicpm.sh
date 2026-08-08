#!/usr/bin/env bash
# 用途：在 WSL 中以前台方式启动 MiniCPM-o 4.5 AWQ 的 vLLM 服务。
# 使用：export MINICPM_API_KEY='你的密钥'; ./scripts/start_minicpm.sh
# 日志：/opt/minicpm-service/logs/minicpm-o.{stdout,stderr}.log

set -euo pipefail

SERVICE_DIR="/opt/minicpm-service"
VLLM_BIN="${SERVICE_DIR}/venv/bin/vllm"
MODEL_DIR="/mnt/d/AI/models/MiniCPM-o-4_5-AWQ"
LOG_DIR="${SERVICE_DIR}/logs"

if [[ -z "${MINICPM_API_KEY:-}" ]]; then
  echo "错误：请先设置 MINICPM_API_KEY。"
  echo "示例：export MINICPM_API_KEY='请替换为随机且足够长的密钥'"
  exit 1
fi

if [[ ! -x "${VLLM_BIN}" ]]; then
  echo "错误：未找到 vLLM：${VLLM_BIN}"
  exit 1
fi

if [[ ! -d "${MODEL_DIR}" ]]; then
  echo "错误：未找到模型目录：${MODEL_DIR}"
  exit 1
fi

if pgrep -f "${VLLM_BIN} serve ${MODEL_DIR}" >/dev/null; then
  echo "MiniCPM-o 已经在运行。"
  exit 0
fi

mkdir -p "${LOG_DIR}"

# WSL 会在启动命令返回后清理孤立的后台进程，因此服务保持前台运行。
# 请保持当前终端打开，另开一个 WSL 终端执行状态检查或其他操作。
# vLLM 0.26 的 V2 Runner 在当前 WSL 环境中要求 UVA，因此使用兼容的旧 Runner。
# 禁用 FlashInfer 采样器可避免运行时依赖完整 CUDA Toolkit 和 nvcc。
echo "正在启动 MiniCPM-o；按 Ctrl+C 可以停止服务。"
echo "标准输出日志：${LOG_DIR}/minicpm-o.stdout.log"
echo "错误输出日志：${LOG_DIR}/minicpm-o.stderr.log"

exec env \
  VLLM_USE_V2_MODEL_RUNNER=0 \
  VLLM_USE_FLASHINFER_SAMPLER=0 \
  "${VLLM_BIN}" serve "${MODEL_DIR}" \
  --host 0.0.0.0 \
  --port 8000 \
  --api-key "${MINICPM_API_KEY}" \
  --gpu-memory-utilization 0.85 \
  --max-model-len 2048 \
  --trust-remote-code \
  --served-model-name minicpm-o-4.5-awq \
  --max-num-batched-tokens 2048 \
  --allowed-local-media-path /tmp \
  > >(tee "${LOG_DIR}/minicpm-o.stdout.log") \
  2> >(tee "${LOG_DIR}/minicpm-o.stderr.log" >&2)
