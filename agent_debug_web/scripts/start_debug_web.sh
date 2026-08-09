#!/usr/bin/env bash
# 启动独立 Web Debug ROS Action Client，不加载任何 Agent 内部模块。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
source "${root}/llm_agent/install-ros/setup.bash"
set -u
export PYTHONPATH="${root}:${PYTHONPATH:-}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
exec /opt/minicpm-service/venv/bin/python -m agent_debug_web
