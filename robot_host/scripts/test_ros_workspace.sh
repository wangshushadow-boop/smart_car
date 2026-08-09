#!/usr/bin/env bash
# 运行树莓派 ROS 包测试并汇总失败详情。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
source "${root}/robot_host/install-ros/setup.bash"
colcon --log-base "${root}/robot_host/log-ros" test \
  --base-paths "${root}/ros_middleware/src" "${root}/robot_host/ros" \
  --build-base "${root}/robot_host/build-ros" \
  --install-base "${root}/robot_host/install-ros" \
  --return-code-on-test-failure
colcon test-result --test-result-base "${root}/robot_host/build-ros" --verbose
