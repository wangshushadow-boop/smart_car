# MCU OTA 升级

本项目使用同一个 STM32 工程构建 Bootloader 和 App，无需修改 CubeMX
`.ioc`。`STM32F407XX_FLASH.ld` 是唯一链接脚本源文件；CMake 配置时会在
构建目录自动生成对应分区的链接脚本。删除构建目录或重新生成 CubeMX 代码后，
重新运行 CMake 即可，不需要手动同步 LD。

## Flash 分区

| 内容 | 地址与大小 | 说明 |
| --- | --- | --- |
| Bootloader | `0x08000000`，64 KiB | 接收、校验和启动 App |
| OTA 元数据 | `0x08010000`，64 KiB | 保存版本、大小、CRC32 和 HMAC |
| App | `0x08020000`，384 KiB | 小车主程序 |

不要把 `small_car_f407.bin` 写入 `0x08000000`，否则会覆盖 Bootloader。

## 构建固件

在 PC 上执行：

```powershell
cd small_car_f407
cmake --preset Release
cmake --build --preset Release
```

输出文件：

```text
build/Release/small_car_bootloader.bin
build/Release/small_car_f407.bin
```

## 首次安装

首次必须通过 ST-Link 烧录一次 Bootloader，之后更新 App 不再需要 ST-Link。

如果在树莓派使用 `st-flash`，先从 PC 上传两个固件：

```powershell
ssh ubuntu@192.168.3.85 "mkdir -p ~/small_car_f407/firmware"
scp build/Release/small_car_bootloader.bin `
    build/Release/small_car_f407.bin `
    ubuntu@192.168.3.85:~/small_car_f407/firmware/
```

然后登录树莓派烧录 Bootloader：

```bash
ssh ubuntu@192.168.3.85
cd ~/small_car_f407/ros_middleware/docker
docker compose down
st-info --probe
st-flash --reset write \
  ~/small_car_f407/firmware/small_car_bootloader.bin \
  0x08000000
```

`st-info` 应识别 STM32F407 和 512 KiB Flash；烧录成功时会显示
`Flash written and verified`。

也可以在 STM32CubeProgrammer 中连接 ST-Link，选择
`small_car_bootloader.bin`，将下载地址设为 `0x08000000` 后执行
**Download**。

烧录 Bootloader 后，通过 OTA 安装第一个 App：

```bash
cd ~/small_car_f407/robot_host
./scripts/update_mcu_firmware.sh \
  ~/small_car_f407/firmware/small_car_f407.bin \
  1
```

## 日常升级

先把 App 上传到树莓派，再指定要写入元数据的版本号：

```bash
scp small_car_f407.bin ubuntu@192.168.3.85:/tmp/
ssh ubuntu@192.168.3.85
cd ~/small_car_f407/robot_host
./scripts/update_mcu_firmware.sh /tmp/small_car_f407.bin 2
```

脚本会停止 ROS 容器、释放 USART3、传输固件并重新启动容器。出现
`启动 ACK 未返回，MCU 可能已切换到新应用` 属于复位时末尾 ACK 丢失；
只要随后显示升级完成且 ROS 链路恢复，即表示升级成功。

升级工具会在传输前通过 USART3 查询并打印当前固件版本，传输完成后再次查询。
当前不限制版本号递增，允许重复使用同一版本号。

只查询版本时，先释放被 ROS 容器占用的串口：

```bash
cd ~/small_car_f407/ros_middleware/docker
docker compose down
python3 ../tools/mcu_ota.py \
  --status \
  --device /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00
docker compose up -d
```

查询直接复用 App 与树莓派之间的 USART3，不会进入 Bootloader、不会复位 MCU，
也不需要切换到 USART1。

`sync_ros2_host.ps1` 只部署 ROS 环境，不会烧录 Bootloader，也不会自动执行
MCU OTA。

## 校验与故障恢复

每个传输帧使用 CRC16，完整镜像使用 CRC32 和 HMAC-SHA256。只有全部校验
通过后才写入有效元数据并启动 App。

升级断电或失败时，Bootloader 不会启动不完整 App。重新运行升级命令即可从头
传输。如果 ROS 容器没有自动恢复：

```bash
cd ~/small_car_f407/ros_middleware/docker
docker compose up -d
```

## 生产密钥

仓库内置 HMAC 密钥仅供开发联调。正式发布前必须同步替换 Bootloader 密钥，
并在树莓派保存对应的 32 字节密钥文件：

```bash
python3 tools/mcu_ota.py firmware.bin \
  --version 3 \
  --key-file /secure/ota.key
```

密钥文件不得提交到 Git。
