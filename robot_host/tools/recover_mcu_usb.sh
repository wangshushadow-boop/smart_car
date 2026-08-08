#!/usr/bin/env bash

set -euo pipefail

workspace_dir="/home/ubuntu/small_car_f407"
project_dir="${workspace_dir}/robot_host"
compose_dir="${workspace_dir}/ros_middleware/docker"
request_file="${project_dir}/runtime/mcu_recovery.request"
serial_device="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00"
usb_id="1a86:55d4"

# systemd 可能在同一故障期间收到多次请求，文件锁保证只执行一个恢复流程。
exec 9>"/run/lock/small-car-mcu-recovery.lock"
flock -n 9 || exit 0
rm -f "${request_file}"

echo "[MCU-RECOVERY] stop ROS2 container"
sudo -u ubuntu -H docker compose -f "${compose_dir}/compose.yaml" down || true

echo "[MCU-RECOVERY] reset USB device ${usb_id}"
if command -v usbreset >/dev/null 2>&1; then
  usbreset "${usb_id}" || true
fi

# 即使 ttyACM0 仍存在，也重新授权设备。xHCI 端点损坏时设备节点可能存在但无法写入。
usb_sysfs=""
for device in /sys/bus/usb/devices/*; do
  [[ -f "${device}/idVendor" && -f "${device}/idProduct" ]] || continue
  [[ "$(<"${device}/idVendor")" == "1a86" ]] || continue
  [[ "$(<"${device}/idProduct")" == "55d4" ]] || continue
  usb_sysfs="${device}"
  break
done

if [[ -n "${usb_sysfs}" ]]; then
  echo 0 >"${usb_sysfs}/authorized"
  sleep 1
  echo 1 >"${usb_sysfs}/authorized"
fi

echo "[MCU-RECOVERY] wait for serial device"
for _ in {1..20}; do
  [[ -e "${serial_device}" ]] && break
  sleep 1
done

if [[ ! -e "${serial_device}" ]]; then
  echo "[MCU-RECOVERY] serial device did not return" >&2
  exit 1
fi

echo "[MCU-RECOVERY] recreate ROS2 container"
sudo -u ubuntu -H docker compose -f "${compose_dir}/compose.yaml" up -d \
  --force-recreate

container_id="$(
  sudo -u ubuntu -H docker compose -f "${compose_dir}/compose.yaml" \
    ps -q small_car_ros2
)"
for _ in {1..90}; do
  container_logs="$(docker logs "${container_id}" 2>&1 || true)"
  if grep -Eq "applied and verified [0-9]+ chassis parameters" <<<"${container_logs}" &&
      grep -q "small car base ready" <<<"${container_logs}"; then
    echo "[MCU-RECOVERY] completed; MCU link and base node verified"
    exit 0
  fi
  sleep 1
done

echo "[MCU-RECOVERY] MCU or base node verification timed out" >&2
exit 1
