#!/usr/bin/env bash
# 验证树莓派容器中的唯一 ROS 运行实例和关键控制链路。
set -eo pipefail

fail() {
  echo "ros_health=failed: $*" >&2
  exit 1
}

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -f "${root}/robot_host/install-ros/setup.bash" ]] || \
  fail "ROS 工作区仍在构建"
source /opt/ros/kilted/setup.bash
source "${root}/robot_host/install-ros/setup.bash"
set -u

nodes="$(timeout 10 ros2 node list --no-daemon --spin-time 3 2>/dev/null)" || \
  fail "无法读取 ROS 节点图"

duplicates="$(printf '%s\n' "${nodes}" | sort | uniq -d)"
if [[ -n "${duplicates}" ]]; then
  fail "发现重复节点名: $(printf '%s' "${duplicates}" | tr '\n' ' ')"
fi

for node in /small_car_base /car_agent_client /robot_tool_gateway \
  /behavior_server /collision_monitor; do
  [[ "$(printf '%s\n' "${nodes}" | grep -Fxc "${node}")" -eq 1 ]] || \
    fail "节点数量异常: ${node}; 当前节点=$(printf '%s' "${nodes}" | tr '\n' ' ')"
done

timeout 10 ros2 interface show \
  small_car_interfaces/action/ExecuteRobotTool >/dev/null || \
  fail "ExecuteRobotTool 接口未安装"
timeout 10 ros2 interface show small_car_interfaces/srv/PlayAudio >/dev/null || \
  fail "PlayAudio 接口未安装"
timeout 10 ros2 interface show small_car_interfaces/srv/RunAgent >/dev/null || \
  fail "RunAgent 接口未安装"

tool_action="$(timeout 10 ros2 action info /car/agent/tool_execute 2>/dev/null)" || \
  fail "无法读取 Robot Tool Action"
printf '%s\n' "${tool_action}" | grep -q '^Action servers: 1$' || \
  fail "Robot Tool Gateway Server 数量不是 1"

for node in /controller_server /behavior_server /collision_monitor; do
  state="$(timeout 10 ros2 lifecycle get "${node}" 2>/dev/null)" || \
    fail "无法读取生命周期: ${node}"
  [[ "${state}" == active* ]] || fail "节点未激活: ${node} (${state})"
done

topics="$(timeout 10 ros2 topic list --no-daemon --spin-time 3 2>/dev/null)" || \
  fail "无法读取 ROS Topic 图"
printf '%s\n' "${topics}" | grep -Fxq /car/camera/image/compressed || \
  fail "压缩相机 Topic 不可用"

services="$(timeout 10 ros2 service list -t 2>/dev/null)" || \
  fail "无法读取 ROS Service 图"
printf '%s\n' "${services}" | \
  grep -Fq '/car/audio/enqueue [small_car_interfaces/srv/PlayAudio]' || \
  fail "音频入队 Service 不可用"

echo "ros_health=ok"
