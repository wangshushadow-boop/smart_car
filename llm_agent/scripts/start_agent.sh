#!/usr/bin/env bash
# 启动事件驱动的小车 Agent：ROS 音视频输入 → LangGraph → MiniCPM-o。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
source "${root}/llm_agent/install-ros/setup.bash"
set -u
export PYTHONPATH="${root}:${PYTHONPATH:-}"
# 与树莓派容器保持完全相同的 ROS 2 域和 DDS 实现，避免容器重建后
# Fast DDS/Cyclone DDS 跨实现发现不稳定，只能看到缓存节点却没有 topic 端点。
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
# Agent 只访问本机 Omni 和局域网 ROS 2；启动时关闭 WSL 全局代理，
# 避免 OpenAI/httpx 对 NO_PROXY 通配符解释不一致而把 127.0.0.1 发给代理。
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
agent_python="/opt/minicpm-service/venv/bin/python"
"${agent_python}" -c 'import yaml; from ament_index_python.packages import get_package_share_directory'
exec "${agent_python}" -m llm_agent.agent.run_agent
