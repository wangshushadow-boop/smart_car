/**
 * @file types.hpp
 * @brief 定义树莓派端与 MCU 通信时使用的业务数据类型。
 *
 * 本文件只描述从串口帧解码后的数据，不负责字节序、CRC 或串口读写。
 * 除特别说明外，整数单位与 MCU 协议保持一致，避免协议层使用浮点数。
 */
#ifndef SMALL_CAR_BASE_MCU_TYPES_HPP_
#define SMALL_CAR_BASE_MCU_TYPES_HPP_

#include <cstdint>

namespace small_car {

// 下面这些结构体是 MCU 协议解码后的业务数据，字段单位尽量直接写在命名中。

/** 控制权当前归属，用于判断手柄、上位机和安全逻辑谁在控制底盘。 */
enum class ControlSource : std::uint8_t {
  kNone = 0,
  kHost = 1,
  kPad = 2,
  kSafe = 3,
};

/** MCU 底盘控制模式。 */
enum class ControlMode : std::uint8_t {
  kStop = 0,
  kVelocity = 1,
};

/** 控制量的编码方式：归一化摇杆值或带物理单位的速度值。 */
enum class ControlValueType : std::uint8_t {
  kNormalized = 0,
  kPhysicalVelocity = 1,
};

/** MCU 对下行命令返回的处理结果。 */
enum class AckResult : std::uint8_t {
  kOk = 0,
  kCrcError = 1,
  kLenError = 2,
  kUnsupported = 3,
  kBusy = 4,
};

/** MCU 当前采用的控制源、控制量和前方超声距离。 */
struct ChassisStatus {
  /** MCU 启动后的毫秒计数，溢出后自然回绕。 */
  std::uint32_t mcu_time_ms = 0;
  /** 取值对应 ControlSource。 */
  std::uint8_t source = 0;
  /** true 表示控制输出已使能。 */
  bool enabled = false;
  /** 取值对应 ControlValueType。 */
  std::uint8_t value_type = 0;
  /** 前进控制量；单位取决于 value_type。 */
  std::int16_t forward = 0;
  /** 转向控制量；单位取决于 value_type。 */
  std::int16_t turn = 0;
  /** 超声距离，单位 mm；负值表示当前无有效测量。 */
  std::int16_t ultra_mm = -1;
};

/** 四个电机编码器自 MCU 启动或清零后的累计计数。 */
struct EncoderCounts {
  std::uint32_t mcu_time_ms = 0;
  std::int32_t count_a = 0;
  std::int32_t count_b = 0;
  std::int32_t count_c = 0;
  std::int32_t count_d = 0;
};

/** ICM20948 原始六轴采样值，量程换算由使用者根据 MCU 配置完成。 */
struct ImuRaw {
  std::uint32_t mcu_time_ms = 0;
  std::int16_t ax = 0;
  std::int16_t ay = 0;
  std::int16_t az = 0;
  std::int16_t gx = 0;
  std::int16_t gy = 0;
  std::int16_t gz = 0;
};

/** MCU 各外设的在线状态和汇总错误码。 */
struct DeviceStatus {
  std::uint32_t mcu_time_ms = 0;
  bool pad_ok = false;
  bool imu_ok = false;
  bool ultra_ok = false;
  std::uint8_t error = 0;
};

/** MCU 返回的一个可调底盘参数及其当前值。 */
struct ParamValue {
  std::uint32_t mcu_time_ms = 0;
  std::uint8_t param_id = 0;
  std::int32_t value = 0;
};

/** 下行命令的确认信息。 */
struct Ack {
  /** 被确认的消息类型。 */
  std::uint8_t ack_msg = 0;
  /** 被确认消息的序号。 */
  std::uint8_t ack_seq = 0;
  /** 取值对应 AckResult。 */
  std::uint8_t result = 0;
};

}  // namespace small_car

#endif  // SMALL_CAR_BASE_MCU_TYPES_HPP_
