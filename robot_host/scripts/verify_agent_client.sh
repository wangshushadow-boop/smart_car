#!/usr/bin/env bash
# 验证生成的 Action、C++ 客户端安装结果和 launch 装配，不访问真实硬件。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
source "${root}/robot_host/install-ros/setup.bash"
test -x "${root}/robot_host/install-ros/agent_client/lib/agent_client/agent_client_node"
test -x "${root}/robot_host/install-ros/robot_tool_gateway/lib/robot_tool_gateway/robot_tool_gateway_node"
ros2 interface show small_car_interfaces/srv/RunAgent
ros2 interface show small_car_interfaces/action/ExecuteRobotTool
ros2 interface show small_car_interfaces/srv/PlayAudio
ros2 launch agent_client agent_client.launch.py --show-args
ros2 launch small_car_nav2 system.launch.py --show-args
