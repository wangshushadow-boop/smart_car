/**
 * @file protocol.cpp
 * @brief 实现树莓派与 STM32 二进制协议的编码、解码和流式拆帧。
 *
 * 所有多字节整数均按小端序传输；CRC 覆盖版本字段到负载末尾，不包含同步头。
 */
#include "small_car_base/protocol/protocol.hpp"

#include <algorithm>
#include <chrono>
#include <iterator>
#include <stdexcept>

namespace small_car {
namespace {

constexpr std::size_t kHeaderSize = 6;
constexpr std::size_t kMinFrameSize = 8;
constexpr std::uint8_t kSyncBytes[] = {kSync0, kSync1};
constexpr std::uint8_t kParamOpSet = 1;
constexpr std::uint8_t kParamOpGet = 2;

// 协议统一使用小端序，和 MCU 侧结构体拆包保持一致。
void PutU16(std::vector<std::uint8_t>* data, std::uint16_t value) {
  data->push_back(static_cast<std::uint8_t>(value & 0xFF));
  data->push_back(static_cast<std::uint8_t>((value >> 8) & 0xFF));
}

void PutI16(std::vector<std::uint8_t>* data, std::int16_t value) {
  PutU16(data, static_cast<std::uint16_t>(value));
}

void PutU32(std::vector<std::uint8_t>* data, std::uint32_t value) {
  data->push_back(static_cast<std::uint8_t>(value & 0xFF));
  data->push_back(static_cast<std::uint8_t>((value >> 8) & 0xFF));
  data->push_back(static_cast<std::uint8_t>((value >> 16) & 0xFF));
  data->push_back(static_cast<std::uint8_t>((value >> 24) & 0xFF));
}

void PutI32(std::vector<std::uint8_t>* data, std::int32_t value) {
  PutU32(data, static_cast<std::uint32_t>(value));
}

std::uint16_t ReadU16(const std::vector<std::uint8_t>& data, std::size_t offset) {
  return static_cast<std::uint16_t>(data[offset]) |
         (static_cast<std::uint16_t>(data[offset + 1]) << 8);
}

std::int16_t ReadI16(const std::vector<std::uint8_t>& data, std::size_t offset) {
  return static_cast<std::int16_t>(ReadU16(data, offset));
}

std::uint32_t ReadU32(const std::vector<std::uint8_t>& data, std::size_t offset) {
  return static_cast<std::uint32_t>(data[offset]) |
         (static_cast<std::uint32_t>(data[offset + 1]) << 8) |
         (static_cast<std::uint32_t>(data[offset + 2]) << 16) |
         (static_cast<std::uint32_t>(data[offset + 3]) << 24);
}

std::int32_t ReadI32(const std::vector<std::uint8_t>& data, std::size_t offset) {
  return static_cast<std::int32_t>(ReadU32(data, offset));
}

void RequirePayloadSize(const std::vector<std::uint8_t>& payload, std::size_t size) {
  if (payload.size() != size) {
    throw std::runtime_error("payload size mismatch");
  }
}

// 串口流中可能出现半包或噪声。若最后一个字节正好是帧头首字节 AA，
// 需要保留下来，等待下一次 Feed() 拼成 AA 55。
void DropNoise(std::vector<std::uint8_t>* buffer) {
  if (!buffer->empty() && buffer->back() == kSync0) {
    const std::uint8_t tail = buffer->back();
    buffer->clear();
    buffer->push_back(tail);
  } else {
    buffer->clear();
  }
}

}  // namespace

std::uint16_t Crc16CcittFalse(const std::uint8_t* data, std::size_t size) {
  // CRC16-CCITT-FALSE：初值 0xFFFF，多项式 0x1021。
  std::uint16_t crc = 0xFFFF;
  for (std::size_t i = 0; i < size; ++i) {
    crc ^= static_cast<std::uint16_t>(data[i]) << 8;
    for (int bit = 0; bit < 8; ++bit) {
      if ((crc & 0x8000) != 0) {
        crc = static_cast<std::uint16_t>((crc << 1) ^ 0x1021);
      } else {
        crc = static_cast<std::uint16_t>(crc << 1);
      }
    }
  }
  return crc;
}

std::uint16_t Crc16CcittFalse(const std::vector<std::uint8_t>& data) {
  return Crc16CcittFalse(data.data(), data.size());
}

std::uint32_t NowMs() {
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return static_cast<std::uint32_t>(
      std::chrono::duration_cast<std::chrono::milliseconds>(now).count());
}

std::vector<std::uint8_t> EncodeFrame(std::uint8_t msg,
                                      std::uint8_t seq,
                                      const std::vector<std::uint8_t>& payload) {
  if (payload.size() > kMaxPayloadSize) {
    throw std::runtime_error("payload too large");
  }

  std::vector<std::uint8_t> frame;
  frame.reserve(kMinFrameSize + payload.size());
  frame.push_back(kSync0);
  frame.push_back(kSync1);
  frame.push_back(kProtocolVersion);
  frame.push_back(msg);
  frame.push_back(seq);
  frame.push_back(static_cast<std::uint8_t>(payload.size()));
  frame.insert(frame.end(), payload.begin(), payload.end());

  // CRC 覆盖 VER 到 PAYLOAD，不包含 AA 55 帧头，便于接收端重新同步。
  const std::uint16_t crc = Crc16CcittFalse(frame.data() + 2, frame.size() - 2);
  PutU16(&frame, crc);
  return frame;
}

std::vector<std::uint8_t> MakeHeartbeatFrame(std::uint8_t seq,
                                             std::uint32_t host_time_ms) {
  std::vector<std::uint8_t> payload;
  PutU32(&payload, host_time_ms);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kHeartbeat), seq, payload);
}

std::vector<std::uint8_t> MakeStopFrame(std::uint8_t seq, std::uint32_t host_time_ms) {
  std::vector<std::uint8_t> payload;
  PutU32(&payload, host_time_ms);
  payload.push_back(static_cast<std::uint8_t>(ControlMode::kStop));
  payload.push_back(0);
  PutI16(&payload, 0);
  PutI16(&payload, 0);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kControl), seq, payload);
}

std::vector<std::uint8_t> MakeDriveFrame(std::uint8_t seq,
                                         std::int16_t linear_mm_s,
                                         std::int16_t angular_mrad_s,
                                         std::uint32_t host_time_ms) {
  std::vector<std::uint8_t> payload;
  PutU32(&payload, host_time_ms);
  payload.push_back(static_cast<std::uint8_t>(ControlMode::kVelocity));
  payload.push_back(1);
  PutI16(&payload, linear_mm_s);
  PutI16(&payload, angular_mrad_s);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kControl), seq, payload);
}

std::vector<std::uint8_t> MakeServoFrame(std::uint8_t seq,
                                         std::uint16_t upper_us,
                                         std::uint16_t lower_us,
                                         std::uint32_t host_time_ms) {
  std::vector<std::uint8_t> payload;
  PutU32(&payload, host_time_ms);
  PutU16(&payload, upper_us);
  PutU16(&payload, lower_us);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kServo), seq, payload);
}

std::vector<std::uint8_t> MakeParamSetFrame(std::uint8_t seq,
                                            std::uint8_t param_id,
                                            std::int32_t value,
                                            std::uint32_t host_time_ms) {
  std::vector<std::uint8_t> payload;
  PutU32(&payload, host_time_ms);
  payload.push_back(kParamOpSet);
  payload.push_back(param_id);
  PutI32(&payload, value);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kParam), seq, payload);
}

std::vector<std::uint8_t> MakeParamGetFrame(std::uint8_t seq,
                                            std::uint8_t param_id,
                                            std::uint32_t host_time_ms) {
  std::vector<std::uint8_t> payload;
  PutU32(&payload, host_time_ms);
  payload.push_back(kParamOpGet);
  payload.push_back(param_id);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kParam), seq, payload);
}

std::vector<std::uint8_t> MakeTelemetryConfigFrame(std::uint8_t seq,
                                                   std::uint16_t mask) {
  std::vector<std::uint8_t> payload;
  PutU16(&payload, mask);
  return EncodeFrame(static_cast<std::uint8_t>(Msg::kTelemetryConfig), seq,
                     payload);
}

std::optional<DecodedMessage> DecodePayload(const Frame& frame) {
  const auto& payload = frame.payload;
  // 这里只解析 MCU 会上传给树莓派的消息；树莓派下发的命令不需要反向解析。
  switch (static_cast<Msg>(frame.msg)) {
    case Msg::kChassisStatus: {
      RequirePayloadSize(payload, 13);
      return ChassisStatus{
          ReadU32(payload, 0),
          payload[4],
          payload[5] != 0,
          payload[6],
          ReadI16(payload, 7),
          ReadI16(payload, 9),
          ReadI16(payload, 11),
      };
    }
    case Msg::kEncoderCounts: {
      RequirePayloadSize(payload, 20);
      return EncoderCounts{
          ReadU32(payload, 0),
          ReadI32(payload, 4),
          ReadI32(payload, 8),
          ReadI32(payload, 12),
          ReadI32(payload, 16),
      };
    }
    case Msg::kImuRaw: {
      RequirePayloadSize(payload, 16);
      return ImuRaw{
          ReadU32(payload, 0),
          ReadI16(payload, 4),
          ReadI16(payload, 6),
          ReadI16(payload, 8),
          ReadI16(payload, 10),
          ReadI16(payload, 12),
          ReadI16(payload, 14),
      };
    }
    case Msg::kDeviceStatus: {
      RequirePayloadSize(payload, 8);
      return DeviceStatus{
          ReadU32(payload, 0),
          payload[4] != 0,
          payload[5] != 0,
          payload[6] != 0,
          payload[7],
      };
    }
    case Msg::kAck: {
      RequirePayloadSize(payload, 3);
      return Ack{payload[0], payload[1], payload[2]};
    }
    case Msg::kParamValue: {
      RequirePayloadSize(payload, 9);
      return ParamValue{
          ReadU32(payload, 0),
          payload[4],
          ReadI32(payload, 5),
      };
    }
    default:
      return std::nullopt;
  }
}

std::vector<Frame> FrameParser::Feed(const std::uint8_t* data, std::size_t size) {
  if (data == nullptr || size == 0) {
    return {};
  }

  buffer_.insert(buffer_.end(), data, data + size);

  std::vector<Frame> frames;
  while (true) {
    // 串口是字节流，没有天然包边界，所以每次都先搜索 AA 55 帧头。
    auto sync = std::search(buffer_.begin(), buffer_.end(), std::begin(kSyncBytes),
                            std::end(kSyncBytes));
    if (sync == buffer_.end()) {
      DropNoise(&buffer_);
      break;
    }
    if (sync != buffer_.begin()) {
      buffer_.erase(buffer_.begin(), sync);
    }
    if (buffer_.size() < kMinFrameSize) {
      break;
    }

    const std::uint8_t version = buffer_[2];
    const std::uint8_t msg = buffer_[3];
    const std::uint8_t seq = buffer_[4];
    const std::uint8_t length = buffer_[5];
    if (length > kMaxPayloadSize) {
      // 长度字段异常时丢掉一个字节，继续寻找下一个可能的帧头。
      buffer_.erase(buffer_.begin());
      continue;
    }

    const std::size_t frame_size = kHeaderSize + length + 2;
    if (buffer_.size() < frame_size) {
      break;
    }

    const std::uint16_t expected_crc = ReadU16(buffer_, kHeaderSize + length);
    const std::uint16_t actual_crc =
        Crc16CcittFalse(buffer_.data() + 2, 4 + length);

    if (version == kProtocolVersion && expected_crc == actual_crc) {
      // 版本和 CRC 都正确才交给上层，避免算法层拿到坏数据。
      Frame frame;
      frame.msg = msg;
      frame.seq = seq;
      frame.payload.assign(buffer_.begin() + kHeaderSize,
                           buffer_.begin() + kHeaderSize + length);
      frames.push_back(std::move(frame));
    }

    buffer_.erase(buffer_.begin(), buffer_.begin() + frame_size);
  }

  return frames;
}

std::vector<Frame> FrameParser::Feed(const std::vector<std::uint8_t>& data) {
  if (data.empty()) {
    return {};
  }
  return Feed(data.data(), data.size());
}

void FrameParser::Reset() {
  buffer_.clear();
}

std::vector<std::uint8_t> PacketCodec::Heartbeat() {
  return MakeHeartbeatFrame(NextSeq());
}

std::vector<std::uint8_t> PacketCodec::Stop() {
  return MakeStopFrame(NextSeq());
}

std::vector<std::uint8_t> PacketCodec::Drive(std::int16_t linear_mm_s,
                                             std::int16_t angular_mrad_s) {
  return MakeDriveFrame(NextSeq(), linear_mm_s, angular_mrad_s);
}

std::vector<std::uint8_t> PacketCodec::Servo(std::uint16_t upper_us,
                                             std::uint16_t lower_us) {
  return MakeServoFrame(NextSeq(), upper_us, lower_us);
}

std::vector<std::uint8_t> PacketCodec::ParamSet(std::uint8_t param_id,
                                                std::int32_t value) {
  return MakeParamSetFrame(NextSeq(), param_id, value);
}

std::vector<std::uint8_t> PacketCodec::ParamGet(std::uint8_t param_id) {
  return MakeParamGetFrame(NextSeq(), param_id);
}

std::vector<std::uint8_t> PacketCodec::TelemetryConfig(std::uint16_t mask) {
  return MakeTelemetryConfigFrame(NextSeq(), mask);
}

std::uint8_t PacketCodec::NextSeq() {
  // 序号自然溢出即可形成 0-255 循环，用来对应 MCU 的 ACK。
  const std::uint8_t seq = seq_;
  seq_ = static_cast<std::uint8_t>(seq_ + 1);
  return seq;
}

}  // namespace small_car
