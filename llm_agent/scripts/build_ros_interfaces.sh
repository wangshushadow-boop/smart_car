#!/usr/bin/env bash
# 构建 Agent Server 和 Web Debug 共用的 ROS 接口。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source /opt/ros/kilted/setup.bash
colcon --log-base "${root}/llm_agent/log-ros" build \
  --base-paths "${root}/ros_middleware/src" \
  --build-base "${root}/llm_agent/build-ros" \
  --install-base "${root}/llm_agent/install-ros" \
  --symlink-install
