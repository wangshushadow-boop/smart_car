#!/usr/bin/env bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
# 按名称统一启动一个或多个独立本地模型；不启动 Agent。
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python="${LLM_AGENT_PYTHON:-${root}/llm_agent/py_env/venvs/agent/bin/python}"
export PYTHONPATH="${root}:${PYTHONPATH:-}"
# 不传参数时只显示帮助，避免用户无意中加载大型模型。
if (($# == 0)); then
  set -- --help
fi
exec "${python}" "${root}/llm_agent/scripts/start_models.py" "$@"
