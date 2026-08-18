#!/usr/bin/env bash
# 启动统一全模态 ROS Service Server：ROS Service → Runtime → 模型。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# 可选的本地密钥文件。它被 Git 忽略，只允许保存 KEY=value 形式的环境变量。
agent_env_file="${root}/llm_agent/.env"
if [[ -f "${agent_env_file}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${agent_env_file}"
  set +a
fi
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
agent_python="${LLM_AGENT_PYTHON:-${root}/llm_agent/py_env/venvs/agent/bin/python}"
"${agent_python}" -c 'import yaml; from ament_index_python.packages import get_package_share_directory'
exec "${agent_python}" -m llm_agent.app.run_agent
