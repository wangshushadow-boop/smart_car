/**
 * @file protocol.hpp
 * @brief 声明树莓派与 STM32 之间的二进制串口协议编解码接口。
 *
 * 协议层负责帧格式、CRC、大小端转换和粘包/半包处理，不直接访问串口。
 * 协议字段必须与 MCU 端 raspi_link 模块保持一致。
 */
#ifndef SMALL_CAR_BASE_PROTOCOL_PROTOCOL_HPP_
#define SMALL_CAR_BASE_PROTOCOL_PROTOCOL_HPP_

#include <cstddef>
#include <cstdint>
#include <optional>
#include <variant>
#include <vector>

#include "small_car_base/mcu/types.hpp"

namespace small_car {

/** 当前协议版本。修改帧结构时必须同步升级 MCU 端版本。 */
constexpr std::uint8_t kProtocolVersion = 0x03;
/** 两字节同步头，用于在噪声或丢字节后重新定位帧边界。 */
constexpr std::uint8_t kSync0 = 0xAA;
constexpr std::uint8_t kSync1 = 0x55;
/** 单帧负载上限，用于限制缓存和异常长度。 */
constexpr std::size_t kMaxPayloadSize = 64;

/** 消息类型：0x01-0x7F 为树莓派下发，0x80 以上为 MCU 上传。 */
enum class Msg : std::uint8_t {
  kControl = 0x01,
  kServo = 0x02,
  kHeartbeat = 0x03,
  kParam = 0x04,
  kTelemetryConfig = 0x05,
  kOtaEnter = 0x06,
  kOtaInfo = 0x07,
  kChassisStatus = 0x81,
  kEncoderCounts = 0x82,
  kImuRaw = 0x83,
  kDeviceStatus = 0x84,
  kAck = 0x85,
  kParamValue = 0x88,
  kOtaInfoValue = 0x89,
};

/** MCU 周期遥测开关位，可组合后通过 kTelemetryConfig 下发。 */
enum Telemetry : std::uint16_t {
  kTelemetryChassis = 1U << 0,
  kTelemetryEncoder = 1U << 1,
  kTelemetryImu = 1U << 2,
  kTelemetryDevice = 1U << 3,
};

/** 校验通过后的原始协议帧。 */
struct Frame {
  /** 原始消息类型，保留为 uint8_t 以便忽略或记录未知消息。 */
  std::uint8_t msg = 0;
  /** 帧序号由发送方递增，用于匹配 ACK 和排查丢帧。 */
  std::uint8_t seq = 0;
  /** 不含帧头、版本、类型、序号、长度和 CRC 的负载。 */
  std::vector<std::uint8_t> payload;
};

/** 所有当前支持解码的 MCU 上行消息。 */
using DecodedMessage =
    std::variant<ChassisStatus, EncoderCounts, ImuRaw, DeviceStatus, Ack,
                 ParamValue>;

/** 计算协议使用的 CRC16-CCITT-FALSE。 */
std::uint16_t Crc16CcittFalse(const std::uint8_t* data, std::size_t size);
std::uint16_t Crc16CcittFalse(const std::vector<std::uint8_t>& data);

/** @return 主机单调时钟的低 32 位毫秒数。 */
std::uint32_t NowMs();

/** 将消息类型、序号和负载封装为可直接写入串口的完整帧。 */
std::vector<std::uint8_t> EncodeFrame(std::uint8_t msg,
                                      std::uint8_t seq,
                                      const std::vector<std::uint8_t>& payload);

/** 以下 Make* 函数构造指定业务命令，并显式使用调用者提供的帧序号。 */
std::vector<std::uint8_t> MakeHeartbeatFrame(std::uint8_t seq,
                                             std::uint32_t host_time_ms = NowMs());
std::vector<std::uint8_t> MakeStopFrame(std::uint8_t seq,
                                        std::uint32_t host_time_ms = NowMs());
std::vector<std::uint8_t> MakeDriveFrame(std::uint8_t seq,
                                         std::int16_t linear_mm_s,
                                         std::int16_t angular_mrad_s,
                                         std::uint32_t host_time_ms = NowMs());
std::vector<std::uint8_t> MakeServoFrame(std::uint8_t seq,
                                         std::uint16_t upper_us,
                                         std::uint16_t lower_us,
                                         std::uint32_t host_time_ms = NowMs());
std::vector<std::uint8_t> MakeParamSetFrame(std::uint8_t seq,
                                            std::uint8_t param_id,
                                            std::int32_t value,
                                            std::uint32_t host_time_ms = NowMs());
std::vector<std::uint8_t> MakeParamGetFrame(std::uint8_t seq,
                                            std::uint8_t param_id,
                                            std::uint32_t host_time_ms = NowMs());
std::vector<std::uint8_t> MakeTelemetryConfigFrame(std::uint8_t seq,
                                                   std::uint16_t mask);

/**
 * @brief 将一帧负载解析为业务结构体。
 * @return 类型和长度有效时返回对应结构体，否则返回 std::nullopt。
 */
std::optional<DecodedMessage> DecodePayload(const Frame& frame);

/** 增量式帧解析器，可处理半包、粘包、噪声和 CRC 错误。 */
class FrameParser {
 public:
  /** 喂入任意长度字节流，返回本次新解析出的全部完整帧。 */
  std::vector<Frame> Feed(const std::uint8_t* data, std::size_t size);
  std::vector<Frame> Feed(const std::vector<std::uint8_t>& data);
  /** 丢弃尚未组成完整帧的缓存数据。 */
  void Reset();

 private:
  /** 跨 Read() 调用保存的不完整串口数据。 */
  std::vector<std::uint8_t> buffer_;
};

/** 为业务调用者自动维护发送序号的命令编码器。 */
class PacketCodec {
 public:
  /** 以下接口负责自动递增 seq，调用方只需提供业务参数。 */
  std::vector<std::uint8_t> Heartbeat();
  std::vector<std::uint8_t> Stop();
  std::vector<std::uint8_t> Drive(std::int16_t linear_mm_s,
                                  std::int16_t angular_mrad_s);
  std::vector<std::uint8_t> Servo(std::uint16_t upper_us,
                                  std::uint16_t lower_us);
  std::vector<std::uint8_t> ParamSet(std::uint8_t param_id, std::int32_t value);
  std::vector<std::uint8_t> ParamGet(std::uint8_t param_id);
  std::vector<std::uint8_t> TelemetryConfig(std::uint16_t mask);

 private:
  /** 返回当前序号并推进到下一值；溢出后按协议自然回绕。 */
  std::uint8_t NextSeq();

  /** 下一帧使用的发送序号。 */
  std::uint8_t seq_ = 0;
};

}  // namespace small_car

#endif  // SMALL_CAR_BASE_PROTOCOL_PROTOCOL_HPP_
