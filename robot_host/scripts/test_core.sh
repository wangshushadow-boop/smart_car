#!/usr/bin/env bash
# 构建并测试不依赖 ROS 的 robot_host Core。
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cmake -S "${root}/robot_host" -B "${root}/robot_host/build"
cmake --build "${root}/robot_host/build"
ctest --test-dir "${root}/robot_host/build" --output-on-failure
