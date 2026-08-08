/**
 * @file car_client.hpp
 * @brief 声明面向应用层的 STM32 小车通信客户端。
 *
 * CarClient 组合串口、帧解析器和命令编码器，为 CLI、监视工具和 ROS 2
 * 桥接节点提供统一接口。类本身不创建线程，调用者必须周期调用 Poll()。
 */
#ifndef SMALL_CAR_BASE_MCU_CAR_CLIENT_HPP_
#define SMALL_CAR_BASE_MCU_CAR_CLIENT_HPP_

#include <cstdint>
#include <optional>
#include <string>

#include "small_car_base/mcu/types.hpp"
#include "small_car_base/protocol/protocol.hpp"
#include "small_car_base/transport/serial_port.hpp"

namespace small_car {

/** 上位机访问 MCU 的同步客户端；一个实例对应一个串口设备。 */
class CarClient {
 public:
  /** 打开串口并清空旧解析状态。 */
  bool Open(const std::string& device, int baudrate = 115200);
  /** 关闭串口。 */
  void Close();
  /** @return 底层串口当前是否打开。 */
  bool IsOpen() const;

  /** 以下 Send* 方法只负责发送命令，处理结果通过后续 ACK 获得。 */
  bool SendHeartbeat();
  bool SendStop();
  bool SendDrive(std::int16_t linear_mm_s, std::int16_t angular_mrad_s);
  bool SendServo(std::uint16_t upper_us, std::uint16_t lower_us);
  bool SendParamSet(std::uint8_t param_id, std::int32_t value);
  bool SendParamGet(std::uint8_t param_id);
  bool SendTelemetryConfig(std::uint16_t mask);

  /** 从串口读取可用数据，解析完整帧并更新各消息类型的最近值缓存。 */
  void Poll();

  /** 以下 Get* 方法返回最近一次收到的对应消息；从未收到时返回 std::nullopt。 */
  std::optional<ChassisStatus> GetChassisStatus() const;
  std::optional<EncoderCounts> GetEncoderCounts() const;
  std::optional<ImuRaw> GetImuRaw() const;
  std::optional<DeviceStatus> GetDeviceStatus() const;
  std::optional<ParamValue> GetParamValue() const;
  /** 返回并清空最近一次参数回读，便于区分新旧响应。 */
  std::optional<ParamValue> TakeParamValue();
  std::optional<Ack> GetLastAck() const;

 private:
  /** 对底层串口 Write() 的统一入口。 */
  bool SendBytes(const std::vector<std::uint8_t>& data);
  /** 解码一帧并覆盖对应消息类型的最近值缓存。 */
  void HandleFrame(const Frame& frame);

  /** 串口传输、命令编码和流式解析三个相互独立的基础组件。 */
  SerialPort serial_;
  PacketCodec codec_;
  FrameParser parser_;

  /** 各上行消息只保留最近值；需要历史数据时由上层自行记录。 */
  std::optional<ChassisStatus> chassis_status_;
  std::optional<EncoderCounts> encoder_counts_;
  std::optional<ImuRaw> imu_raw_;
  std::optional<DeviceStatus> device_status_;
  std::optional<ParamValue> param_value_;
  std::optional<Ack> last_ack_;
};

}  // namespace small_car

#endif  // SMALL_CAR_BASE_MCU_CAR_CLIENT_HPP_
