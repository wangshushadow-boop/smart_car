#!/usr/bin/env bash
# 在与部署一致的 ROS 和模型 Python 环境中运行 Agent 测试。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
source "${root}/llm_agent/install-ros/setup.bash"
export PYTHONPATH="${root}:${PYTHONPATH:-}"
/opt/minicpm-service/venv/bin/python -m unittest discover \
  -s "${root}/llm_agent/tests" -v
/opt/minicpm-service/venv/bin/python -m unittest discover \
  -s "${root}/agent_debug_web/tests" -v
