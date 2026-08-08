#!/usr/bin/env bash
set -e

# 停止 ROS 容器，释放 MCU 串口。
cd "$HOME/small_car_f407/ros_middleware/docker"
trap 'docker compose up -d' EXIT
docker compose down

# 使用 USART3 写入应用固件。第二个参数是递增的固件版本号。
python3 ../tools/mcu_ota.py "$1" --version "$2" --device /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00
