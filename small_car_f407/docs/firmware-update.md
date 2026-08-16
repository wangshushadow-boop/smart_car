# 固件升级

## 首次烧录

OTA 依赖 Bootloader。新板或 Bootloader 变更时，先用 ST-Link 烧录：

```bash
cd small_car_f407
cmake --preset Release
cmake --build --preset Release
```

产物：

```text
build/Release/small_car_bootloader.bin  -> 0x08000000
build/Release/small_car_f407.bin        -> 0x08020000
```

Flash 布局：Bootloader `0x08000000`（64 KiB）、OTA 元数据 `0x08010000`（64 KiB 扇区）、App `0x08020000..0x0807FFFF`（384 KiB）。首次烧录后应执行一次 OTA，使元数据包含有效镜像信息。

连接 ST-Link 后烧录 Bootloader：

```bash
st-info --probe
st-flash --reset write \
  small_car_f407/build/Release/small_car_bootloader.bin 0x08000000
```

不要把 `small_car_f407.bin` 写到 `0x08000000`，否则会覆盖 Bootloader。

树莓派工作区统一为：

```text
~/smart_car/
├── robot_host/
├── ros_middleware/
└── small_car_f407/
    ├── scripts/mcu_ota.py
    └── build/Release/small_car_f407.bin
```

Windows 上运行 `robot_host/scripts/sync_ros2_host.ps1` 会同步 OTA 工具；如果本机已有
`small_car_f407/build/Release/small_car_f407.bin`，也会把它上传到上述对应路径。同步脚本
不会自动烧录 MCU。
```bash
.\robot_host\scripts\sync_ros2_host.ps
```

## 查询版本

先停止 ROS 容器释放串口：

```bash
cd ~/smart_car/ros_middleware/docker
docker compose down
cd ~/smart_car
python3 small_car_f407/scripts/mcu_ota.py --status \
  --device /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00
```

## 日常 OTA

推荐使用包装脚本，它会自动停止并恢复 ROS 容器：
同步pc编译的固件
```bash
.\robot_host\scripts\sync_ros2_host.ps
```

```bash
cd ~/smart_car
./small_car_f407/scripts/update_mcu_firmware.sh \
  small_car_f407/build/Release/small_car_f407.bin 2
```

版本号用于识别固件，允许重复，但建议单调递增。若直接调用 Python 工具，升级完成后需手动恢复服务：

```bash
cd ~/smart_car/ros_middleware/docker
docker compose up -d
docker compose logs --tail=100
```

## 密钥

未指定 `--key-file` 时工具使用仓库中的开发密钥，只适合开发。生产部署必须同时替换 Bootloader 内的 32 字节 HMAC 密钥，并执行：

```bash
python3 small_car_f407/scripts/mcu_ota.py firmware.bin --version 3 \
  --key-file /secure/path/ota.key --device /dev/small_car_mcu
```

## 恢复

- 升级中断：重新运行同一升级命令；Bootloader 会保持等待状态。
- 首次只烧录了 Bootloader 或 App 无法启动：直接调用 Python 工具并增加 `--bootloader-ready`，跳过 App 复位握手。
- 串口消失：重新插拔 USB，或在仓库根目录运行 `sudo ./robot_host/tools/recover_mcu_usb.sh`。
- Bootloader 损坏或密钥不一致：只能使用 ST-Link 重新烧录 Bootloader。

协议字段、状态码和认证算法见 [串口协议](../../robot_host/docs/protocol.md#ota-子协议)。
