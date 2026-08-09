#!/usr/bin/env bash
# 构建树莓派 ROS 业务节点和共享接口，供本机或容器联调使用。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
colcon --log-base "${root}/robot_host/log-ros" build \
  --base-paths "${root}/ros_middleware/src" "${root}/robot_host/ros" \
  --build-base "${root}/robot_host/build-ros" \
  --install-base "${root}/robot_host/install-ros" \
  --symlink-install
