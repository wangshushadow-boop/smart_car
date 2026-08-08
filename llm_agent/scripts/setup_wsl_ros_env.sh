#!/usr/bin/env bash
# 用途：进入可与树莓派通信的 ROS 2 Kilted 终端。
# 使用：bash scripts/setup_wsl_ros_env.sh [树莓派IP]
# 示例：bash scripts/setup_wsl_ros_env.sh 192.168.3.85

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
ros_setup="/opt/ros/kilted/setup.bash"
workspace_setup="${project_dir}/install-ros/setup.bash"
raspberry_pi_ip="${1:-${ROS_STATIC_PEERS:-}}"

if [[ ! -f "${ros_setup}" ]]; then
  echo "错误：未找到 ROS 2 Kilted：${ros_setup}"
  exit 1
fi

set +u
source "${ros_setup}"
if [[ -f "${workspace_setup}" ]]; then
  source "${workspace_setup}"
fi
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY

# mirrored networking 下优先使用局域网多播发现；静态 peer 用于无线网络
# 禁止多播或发现不稳定时的单播补充。没有提供 IP 时不保留旧值。
if [[ -n "${raspberry_pi_ip}" ]]; then
  export ROS_STATIC_PEERS="${raspberry_pi_ip}"
else
  unset ROS_STATIC_PEERS
fi

timeout 5 ros2 daemon stop >/dev/null 2>&1 || true
timeout 10 ros2 daemon start >/dev/null 2>&1 || true

echo "ROS 2 Kilted 通信环境已加载。"
echo "项目目录：${project_dir}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION}"
echo "ROS_AUTOMATIC_DISCOVERY_RANGE=系统默认（局域网发现）"
echo "ROS_STATIC_PEERS=${ROS_STATIC_PEERS:-未设置，仅使用局域网发现}"
echo "可以执行：ros2 topic list --no-daemon --spin-time 5"

exec zsh -i
