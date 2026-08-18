#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
agent_dir="$(cd -- "${script_dir}/.." && pwd)"
workspace_root="$(cd -- "${agent_dir}/.." && pwd)"
ros_setup="/opt/ros/kilted/setup.bash"
workspace_setup="${agent_dir}/install-ros/setup.bash"

raspberry_pi_ip="${ROS_STATIC_PEERS:-}"
build_workspace=true
check_only=false

usage() {
  echo "Usage: $0 [raspberry-pi-ip] [--no-build] [--check]"
}

while (($# > 0)); do
  case "$1" in
    --no-build)
      build_workspace=false
      ;;
    --check)
      check_only=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -* )
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "${raspberry_pi_ip}" && "${raspberry_pi_ip}" != "$1" ]]; then
        echo "Raspberry Pi IP was specified more than once" >&2
        exit 2
      fi
      raspberry_pi_ip="$1"
      ;;
  esac
  shift
done

for command_name in colcon timeout zsh; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing command: ${command_name}" >&2
    exit 1
  fi
done
if [[ ! -f "${ros_setup}" ]]; then
  echo "ROS 2 Kilted setup was not found: ${ros_setup}" >&2
  exit 1
fi

set +u
source "${ros_setup}"
set -u

if [[ "${build_workspace}" == true ]]; then
  # 删除接口定义时，CMake 的缓存不会自动清理旧 rosidl 生成文件。
  # 这三个目录均由本脚本独占，重建前清理才能保证安装空间与源码一致。
  rm -rf -- "${agent_dir}/build-ros" "${agent_dir}/install-ros" "${agent_dir}/log-ros"
  cd "${workspace_root}"
  colcon --log-base "${agent_dir}/log-ros" build \
    --base-paths "${workspace_root}/ros_middleware/src" \
    --build-base "${agent_dir}/build-ros" \
    --install-base "${agent_dir}/install-ros" \
    --symlink-install
fi

if [[ ! -f "${workspace_setup}" ]]; then
  echo "ROS workspace is not built: ${workspace_setup}" >&2
  exit 1
fi

set +u
source "${workspace_setup}"
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY
if [[ -n "${raspberry_pi_ip}" ]]; then
  export ROS_STATIC_PEERS="${raspberry_pi_ip}"
else
  unset ROS_STATIC_PEERS
fi

timeout 5 ros2 daemon stop >/dev/null 2>&1 || true
timeout 10 ros2 daemon start >/dev/null 2>&1 || true

python3 -c "import yaml; from small_car_interfaces.srv import RunAgent; from small_car_interfaces.msg import AgentContent"
ros2 pkg prefix small_car_interfaces >/dev/null

echo "WSL ROS 2 environment refreshed"
echo "workspace=${workspace_root}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION}"
echo "ROS_STATIC_PEERS=${ROS_STATIC_PEERS:-<multicast-only>}"

if [[ "${check_only}" == true ]]; then
  timeout 10 ros2 topic list --no-daemon --spin-time 3 >/dev/null
  echo "environment_check=ok"
  exit 0
fi

cd "${workspace_root}"
exec zsh -i
