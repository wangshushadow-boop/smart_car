# 树莓派—MCU 串口协议

本文是 USART3 协议 v3 的操作与联调依据。实现必须同步维护：

- 上位机：`robot_host/core/small_car_base/protocol`
- MCU App：`small_car_f407/Core/Modules/Comm/Src/raspi_link.c`
- MCU Bootloader：`small_car_f407/Bootloader/Src/main.c`

## 传输与帧格式

- 串口：115200 baud、8 data bits、no parity、1 stop bit（8N1）。
- 多字节整数：小端序；有符号数使用二进制补码。
- 单帧负载：最多 64 字节。

| 偏移 | 长度 | 字段 | 值/说明 |
| ---: | ---: | --- | --- |
| 0 | 1 | `SYNC0` | `0xAA` |
| 1 | 1 | `SYNC1` | `0x55` |
| 2 | 1 | `VER` | `0x03` |
| 3 | 1 | `MSG` | 消息 ID |
| 4 | 1 | `SEQ` | 发送方序号，`0..255` 自然回绕 |
| 5 | 1 | `LEN` | `PAYLOAD` 字节数，`0..64` |
| 6 | `LEN` | `PAYLOAD` | 消息负载 |
| `6+LEN` | 2 | `CRC16` | 小端序 |

CRC 使用 CRC16-CCITT-FALSE：多项式 `0x1021`、初值 `0xFFFF`、不反射、无最终异或。校验范围是 `VER` 到 `PAYLOAD`，不包含同步头和 CRC 本身。

解析器遇到错误版本、超长负载或 CRC 错误时应丢弃当前帧并重新寻找 `AA 55`。App 对 CRC 错误返回 ACK；主机解析器只向业务层交付版本和 CRC 均正确的帧。

## App 消息总表

| ID | 方向 | 名称 | 负载长度 | 响应 |
| --- | --- | --- | ---: | --- |
| `0x01` | 主机→MCU | CONTROL | 10 | ACK |
| `0x02` | 主机→MCU | SERVO | 8 | ACK |
| `0x03` | 主机→MCU | HEARTBEAT | 4 | ACK |
| `0x04` | 主机→MCU | PARAM | 6/10 | PARAM_VALUE（GET）+ ACK |
| `0x05` | 主机→MCU | TELEMETRY_CONFIG | 2 | ACK |
| `0x06` | 主机→MCU | OTA_ENTER | 0 | ACK 后复位 |
| `0x07` | 主机→MCU | OTA_INFO | 0 | OTA_INFO_VALUE |
| `0x81` | MCU→主机 | CHASSIS_STATUS | 13 | 无 |
| `0x82` | MCU→主机 | ENCODER_COUNTS | 20 | 无 |
| `0x83` | MCU→主机 | IMU_RAW | 16 | 无 |
| `0x84` | MCU→主机 | DEVICE_STATUS | 8 | 无 |
| `0x85` | MCU→主机 | ACK | 3（App） | 无 |
| `0x88` | MCU→主机 | PARAM_VALUE | 9 | 无 |
| `0x89` | MCU→主机 | OTA_INFO_VALUE | 16 | 无 |

## App 下行负载

字段偏移均相对 `PAYLOAD[0]`。

### CONTROL `0x01`

| 偏移 | 类型 | 字段 | 单位/取值 |
| ---: | --- | --- | --- |
| 0 | `uint32` | `host_time_ms` | 主机单调时钟低 32 位 |
| 4 | `uint8` | `mode` | `0` 停车，`1` 物理速度 |
| 5 | `uint8` | `enable` | `0` 停车，非零使能 |
| 6 | `int16` | `linear` | mm/s |
| 8 | `int16` | `angular` | mrad/s |

`mode=0` 或 `enable=0` 都会停车。MCU 只接受模式 0/1；有效控制命令超过 300 ms 未刷新即失效。上位机当前按 20 Hz 刷新，并在 ROS 命令超过 500 ms 后主动发停车帧。

### SERVO `0x02`

| 偏移 | 类型 | 字段 | 单位 |
| ---: | --- | --- | --- |
| 0 | `uint32` | `host_time_ms` | ms |
| 4 | `uint16` | `upper_us` | 上舵机脉宽，µs |
| 6 | `uint16` | `lower_us` | 下舵机脉宽，µs |

### HEARTBEAT `0x03`

负载仅含 `uint32 host_time_ms`。当前用于连通性确认，不延长底盘控制看门狗。

### PARAM `0x04`

SET（10 字节）：

| 偏移 | 类型 | 字段 |
| ---: | --- | --- |
| 0 | `uint32` | `host_time_ms` |
| 4 | `uint8` | `op=1` |
| 5 | `uint8` | `param_id` |
| 6 | `int32` | `value` |

GET（6 字节）：`uint32 host_time_ms`、`uint8 op=2`、`uint8 param_id`。成功时 MCU 先发送 PARAM_VALUE，再发送 ACK。

### TELEMETRY_CONFIG `0x05`

负载为 `uint16 mask`，可按位组合：

| 位 | 值 | 遥测 | 默认周期 |
| ---: | ---: | --- | ---: |
| 0 | `0x0001` | CHASSIS_STATUS | 50 ms |
| 1 | `0x0002` | ENCODER_COUNTS | 20 ms |
| 2 | `0x0004` | IMU_RAW | 20 ms |
| 3 | `0x0008` | DEVICE_STATUS | 1000 ms |

MCU 启动默认开启全部四类，上位机连接后再次下发 `0x000F`。

### OTA_ENTER `0x06` 与 OTA_INFO `0x07`

两者负载都为空。OTA_ENTER 先停车并 ACK，约 20 ms 后设置 SRAM 请求字并复位进入 Bootloader。OTA_INFO 在 App 内查询当前镜像元数据。

## App 上行负载

### CHASSIS_STATUS `0x81`

| 偏移 | 类型 | 字段 | 说明 |
| ---: | --- | --- | --- |
| 0 | `uint32` | `mcu_time_ms` | MCU 启动时间 |
| 4 | `uint8` | `source` | 0 无、1 主机、2 手柄、3 安全逻辑 |
| 5 | `uint8` | `enabled` | 0/1 |
| 6 | `uint8` | `value_type` | 0 归一化量，1 物理速度 |
| 7 | `int16` | `forward` | 归一化量或 mm/s |
| 9 | `int16` | `turn` | 归一化量或 mrad/s |
| 11 | `int16` | `ultra_mm` | mm；`-1` 表示无有效测量 |

### ENCODER_COUNTS `0x82`

`uint32 mcu_time_ms` 后依次是 `int32 count_a`、`count_b`、`count_c`、`count_d`，均为 MCU 启动或清零后的累计编码器计数。

### IMU_RAW `0x83`

`uint32 mcu_time_ms` 后依次是六个 `int16`：`ax`、`ay`、`az`、`gx`、`gy`、`gz`。值为 ICM20948 原始 ADC 计数，量程换算由上位机完成。

### DEVICE_STATUS `0x84`

| 偏移 | 类型 | 字段 |
| ---: | --- | --- |
| 0 | `uint32` | `mcu_time_ms` |
| 4 | `uint8` | `pad_ok` |
| 5 | `uint8` | `imu_ok` |
| 6 | `uint8` | `ultra_ok` |
| 7 | `uint8` | `error`，当前固定 0 |

### ACK `0x85`

App ACK 负载为 `ack_msg:uint8`、`ack_seq:uint8`、`result:uint8`。结果：0 成功、1 CRC 错误、2 长度错误、3 不支持、4 忙（保留）。应使用负载中的 `ack_seq` 匹配请求；ACK 自身帧头的 SEQ 是 MCU 上行序号。

### PARAM_VALUE `0x88`

负载为 `mcu_time_ms:uint32`、`param_id:uint8`、`value:int32`。

### OTA_INFO_VALUE `0x89`

| 偏移 | 类型 | 字段 |
| ---: | --- | --- |
| 0 | `uint8` | `valid` |
| 1 | 3 字节 | 保留，置 0 |
| 4 | `uint32` | `version` |
| 8 | `uint32` | `image_size` |
| 12 | `uint32` | `image_crc32` |

## 运行参数编号

参数只保存在 MCU RAM；复位后恢复固件默认值，上位机启动时从 `chassis.yaml` 全量下发。

| ID | YAML 键 | 单位/编码 | 接受范围 |
| ---: | --- | --- | --- |
| 1 | `odom_mm_per_tick_num` | mm/tick 分子，分母 15600 | 1000..5000，越界拒绝 |
| 2 | `gamepad_forward_start` | 0..1000 | 0..1000 |
| 3 | `gamepad_reverse_start` | 0..1000 | 0..1000 |
| 4 | `gamepad_drive_max` | 0..1000 | 0..1000 |
| 5 | `gamepad_turn_start` | 0..1000 | 0..1000 |
| 6 | `gamepad_turn_max` | 0..1000 | 0..1000 |
| 7 | `ultra_near_distance_mm` | mm | 0..5000 |
| 8 | `gyro_lsb_per_dps_x10` | LSB/dps ×10 | 100..300 |
| 9 | `wheel_track_mm` | mm | 0..1000 |
| 10 | `yaw_gyro_weight_permille` | ‰ | 0..1000 |
| 11 | `attitude_gyro_weight_permille` | ‰ | 0..1000 |
| 12 | `imu_roll_offset_mdeg` | mdeg | -30000..30000 |
| 13 | `imu_pitch_offset_mdeg` | mdeg | -30000..30000 |
| 14 | `max_linear_speed_mm_s` | mm/s | 100..3000 |
| 15 | `max_angular_speed_mrad_s` | mrad/s | 100..10000 |
| 16 | `wheel_speed_closed_loop_enabled` | bool | 0 或 1，其他值拒绝 |
| 17 | `wheel_speed_kp_x100` | Kp ×100 | 0..1000 |
| 18 | `wheel_speed_ki_x100` | Ki ×100 | 0..1000 |
| 19 | `wheel_speed_integral_limit` | 控制内部量 | 0..10000 |
| 20 | `wheel_accel_limit_mm_s2` | mm/s² | 50..5000 |
| 21 | `wheel_pwm_min` | 0..1000 | 0..1000 |
| 22 | `wheel_left_output_permille` | ‰ | 500..1500 |
| 23 | `wheel_right_output_permille` | ‰ | 500..1500 |
| 24 | `wheel_turn_start_pwm` | 0..1000 | 0..1000 |

除表中注明“拒绝”的项目外，越界 SET 会被 MCU 钳制到范围边界并返回成功；上位机随后 GET 回读，因此最终 YAML 应使用合法范围内的值。

## OTA 子协议

Bootloader 复用相同帧格式、版本、字节序和 CRC。消息如下：

| ID | 方向 | 名称 | 负载 |
| --- | --- | --- | --- |
| `0x10` | 主机→Boot | HELLO | 空 |
| `0x11` | 主机→Boot | BEGIN | 44 字节 manifest |
| `0x12` | 主机→Boot | DATA | offset + 最多 60 字节数据 |
| `0x13` | 主机→Boot | END | 空 |
| `0x14` | 主机→Boot | BOOT | 空 |
| `0x15` | 主机→Boot | ABORT | 空 |
| `0x85` | Boot→主机 | ACK | 7 字节 |
| `0x90` | Boot→主机 | STATUS | 20 字节 |

BEGIN 负载：`image_size:uint32`、`version:uint32`、`image_crc32:uint32`、`hmac_sha256[32]`。HMAC 输入为前 12 字节 manifest 后紧接完整镜像，算法为 HMAC-SHA256。

DATA 负载：`offset:uint32` 后紧接镜像块。Bootloader 只接受 `offset == next_offset` 且不越过声明的镜像大小；工具当前每块最多 60 字节。

ACK 负载：`ack_msg:uint8`、`ack_seq:uint8`、`status:uint8`、`next_offset:uint32`。Bootloader ACK 帧头 SEQ 与请求相同。状态码：0 成功、1 CRC、2 长度、3 不支持、4 状态错误、5 Flash 错误、6 CRC/HMAC 认证失败、7 范围或偏移错误。

STATUS 负载：

| 偏移 | 类型 | 字段 |
| ---: | --- | --- |
| 0 | `uint8` | Bootloader 状态格式版本，当前 1 |
| 1 | `uint8` | 当前 App 元数据和镜像是否有效 |
| 2 | 2 字节 | 保留 |
| 4 | `uint32` | 最大 App 大小，当前 393216 |
| 8 | `uint32` | `next_offset` |
| 12 | `uint32` | 当前 App 版本 |
| 16 | `uint32` | 当前 App 大小 |

升级流程：App OTA_ENTER → Boot HELLO → BEGIN（擦除 App 区）→ 顺序 DATA → END（校验并写元数据）→ BOOT。只有 END 的 CRC32 和 HMAC-SHA256 都通过后，镜像才会标记有效。更新中断可从 BEGIN 重新开始；不要在擦写期间断开整机电源。

## 联调检查

```bash
ctest --test-dir robot_host/build-host --output-on-failure
python3 small_car_f407/scripts/mcu_ota.py --status --device /dev/small_car_mcu
```

抓包时先验证 `AA 55`、版本、长度与 CRC，再按 MSG 解释负载。协议新增消息只能使用未占用 ID；参数 ID 只能追加，不能改变现有编号或单位。
