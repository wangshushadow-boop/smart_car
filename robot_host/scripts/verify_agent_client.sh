#!/usr/bin/env bash
# 验证生成的 Action、C++ 客户端安装结果和 launch 装配，不访问真实硬件。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
source "${root}/robot_host/install-ros/setup.bash"
test -x "${root}/robot_host/install-ros/agent_client/lib/agent_client/agent_client_node"
ros2 interface show small_car_interfaces/action/RunAgent
ros2 launch agent_client agent_client.launch.py --show-args
