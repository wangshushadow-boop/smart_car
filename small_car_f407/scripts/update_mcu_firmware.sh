#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <firmware.bin> <version>" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(cd "$script_dir/../.." && pwd)"
compose_dir="$workspace_dir/ros_middleware/docker"
ota_tool="$workspace_dir/small_car_f407/scripts/mcu_ota.py"
case "$1" in
  /*) firmware="$1" ;;
  *) firmware="$PWD/$1" ;;
esac
version="$2"

if [ ! -f "$ota_tool" ]; then
  echo "OTA tool not found: $ota_tool" >&2
  exit 1
fi

if [ ! -f "$firmware" ]; then
  echo "Firmware image not found: $firmware" >&2
  exit 1
fi

# 停止 ROS 容器，释放 MCU 串口。
cd "$compose_dir"
trap 'docker compose up -d' EXIT
docker compose down

# 使用 USART3 写入应用固件。第二个参数是递增的固件版本号。
python3 "$ota_tool" "$firmware" --version "$version" \
  --device /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00
