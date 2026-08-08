/**
 * @file protocol_test.cpp
 * @brief 覆盖小车串口协议编码、解码、拆包和异常恢复的单元测试。
 *
 * 测试使用固定字节序列，不需要连接真实 MCU 或串口设备。
 */
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <variant>
#include <vector>

#include "small_car_base/protocol/protocol.hpp"

namespace {

/** 轻量断言辅助函数，失败时抛出异常并由 main 统一报告。 */
void Expect(bool value, const char* message) {
  if (!value) {
    throw std::runtime_error(message);
  }
}

/** 构造一段已知的底盘状态负载，供解码测试复用。 */
std::vector<std::uint8_t> PayloadChassis() {
  return {
      0x64, 0x00, 0x00, 0x00,  // t=100
      0x02,                    // source=PAD
      0x01,                    // enabled=true
      0x00,                    // normalized control value
      0x2C, 0x01,              // forward=300
      0xD8, 0xFF,              // turn=-40
      0x30, 0x02,              // ultra=560
  };
}

/** 使用标准字符串 "123456789" 校验 CRC 参数是否正确。 */
void TestCrc() {
  const char* text = "123456789";
  const auto* bytes = reinterpret_cast<const std::uint8_t*>(text);
  Expect(small_car::Crc16CcittFalse(bytes, 9) == 0x29B1, "crc known value failed");
}

/** 验证完整帧编码后能够无损地被流式解析器还原。 */
void TestEncodeParse() {
  const auto raw = small_car::EncodeFrame(
      static_cast<std::uint8_t>(small_car::Msg::kHeartbeat), 7, {0xD2, 0x04, 0x00, 0x00});
  small_car::FrameParser parser;
  const auto frames = parser.Feed(raw);
  Expect(frames.size() == 1, "frame count mismatch");
  Expect(frames[0].seq == 7, "seq mismatch");
  Expect(frames[0].msg == static_cast<std::uint8_t>(small_car::Msg::kHeartbeat),
         "msg mismatch");
  Expect(frames[0].payload.size() == 4, "payload size mismatch");
}

/** 验证噪声、拆分输入以及尾部单字节同步头的恢复逻辑。 */
void TestNoiseAndSplit() {
  const auto raw = small_car::EncodeFrame(static_cast<std::uint8_t>(small_car::Msg::kAck),
                                          1,
                                          {0x01, 0x09, 0x00});
  small_car::FrameParser parser;
  Expect(parser.Feed(std::vector<std::uint8_t>{0x00, 0x11, 0xAA}).empty(),
         "noise should not produce frame");

  std::vector<std::uint8_t> part1(raw.begin() + 1, raw.begin() + 4);
  Expect(parser.Feed(part1).empty(), "partial frame should not produce frame");

  std::vector<std::uint8_t> part2(raw.begin() + 4, raw.end());
  const auto frames = parser.Feed(part2);
  Expect(frames.size() == 1, "split frame parse failed");

  const auto decoded = small_car::DecodePayload(frames[0]);
  Expect(decoded.has_value(), "ack decode failed");
  const auto* ack = std::get_if<small_car::Ack>(&decoded.value());
  Expect(ack != nullptr, "ack type mismatch");
  Expect(ack->ack_msg == 0x01 && ack->ack_seq == 0x09 && ack->result == 0x00,
         "ack field mismatch");
}

/** 验证 CRC 被破坏的帧不会交给业务层。 */
void TestBadCrcDropped() {
  auto raw = small_car::MakeHeartbeatFrame(2, 1);
  raw.back() ^= 0x01;
  small_car::FrameParser parser;
  Expect(parser.Feed(raw).empty(), "bad crc should be dropped");
}

/** 验证底盘状态每个字段的偏移、符号和字节序。 */
void TestDecodeChassis() {
  const auto raw = small_car::EncodeFrame(
      static_cast<std::uint8_t>(small_car::Msg::kChassisStatus), 3, PayloadChassis());
  small_car::FrameParser parser;
  const auto frames = parser.Feed(raw);
  const auto decoded = small_car::DecodePayload(frames[0]);
  const auto* status = std::get_if<small_car::ChassisStatus>(&decoded.value());
  Expect(status != nullptr, "chassis type mismatch");
  Expect(status->mcu_time_ms == 100, "time mismatch");
  Expect(status->source == 2, "source mismatch");
  Expect(status->enabled, "enabled mismatch");
  Expect(status->value_type == 0, "control value type mismatch");
  Expect(status->forward == 300, "forward mismatch");
  Expect(status->turn == -40, "turn mismatch");
  Expect(status->ultra_mm == 560, "ultra mismatch");
}

/** 验证四轮累计编码器计数的符号和字节序。 */
void TestDecodeEncoderCounts() {
  const auto raw = small_car::EncodeFrame(
      static_cast<std::uint8_t>(small_car::Msg::kEncoderCounts),
      4,
      {
          0xE8, 0x03, 0x00, 0x00,  // t=1000
          0xA0, 0x86, 0x01, 0x00,  // A=100000
          0x38, 0xFF, 0xFF, 0xFF,  // B=-200
          0x2C, 0x01, 0x00, 0x00,  // C=300
          0x70, 0xFE, 0xFF, 0xFF,  // D=-400
      });
  small_car::FrameParser parser;
  const auto frames = parser.Feed(raw);
  const auto decoded = small_car::DecodePayload(frames[0]);
  const auto* counts = std::get_if<small_car::EncoderCounts>(&decoded.value());
  Expect(counts != nullptr, "encoder counts type mismatch");
  Expect(counts->mcu_time_ms == 1000, "encoder counts time mismatch");
  Expect(counts->count_a == 100000, "encoder A count mismatch");
  Expect(counts->count_b == -200, "encoder B count mismatch");
  Expect(counts->count_c == 300, "encoder C count mismatch");
  Expect(counts->count_d == -400, "encoder D count mismatch");
}

/** 验证参数设置和查询帧的操作码、编号与 32 位数值。 */
void TestParamSetGetFrame() {
  const auto set_raw = small_car::MakeParamSetFrame(7, 1, 2410, 1000);
  small_car::FrameParser parser;
  const auto set_frames = parser.Feed(set_raw);
  Expect(set_frames.size() == 1, "param set frame parse failed");
  Expect(set_frames[0].msg == static_cast<std::uint8_t>(small_car::Msg::kParam),
         "param set msg mismatch");
  Expect(set_frames[0].payload.size() == 10, "param set payload size mismatch");
  Expect(set_frames[0].payload[4] == 1, "param set op mismatch");
  Expect(set_frames[0].payload[5] == 1, "param set id mismatch");
  Expect(set_frames[0].payload[6] == 0x6A && set_frames[0].payload[7] == 0x09,
         "param set value mismatch");

  const auto get_raw = small_car::MakeParamGetFrame(8, 1, 1000);
  const auto get_frames = parser.Feed(get_raw);
  Expect(get_frames.size() == 1, "param get frame parse failed");
  Expect(get_frames[0].payload.size() == 6, "param get payload size mismatch");
  Expect(get_frames[0].payload[4] == 2, "param get op mismatch");
  Expect(get_frames[0].payload[5] == 1, "param get id mismatch");
}

/** 验证 MCU 参数回读消息。 */
void TestDecodeParamValue() {
  const auto raw = small_car::EncodeFrame(
      static_cast<std::uint8_t>(small_car::Msg::kParamValue),
      9,
      {
          0xE8, 0x03, 0x00, 0x00,  // t=1000
          0x01,                    // param id
          0x6A, 0x09, 0x00, 0x00,  // value=2410
      });
  small_car::FrameParser parser;
  const auto frames = parser.Feed(raw);
  const auto decoded = small_car::DecodePayload(frames[0]);
  const auto* param = std::get_if<small_car::ParamValue>(&decoded.value());
  Expect(param != nullptr, "param value type mismatch");
  Expect(param->mcu_time_ms == 1000, "param value time mismatch");
  Expect(param->param_id == 1, "param value id mismatch");
  Expect(param->value == 2410, "param value mismatch");
}

/** 验证物理速度控制量按 mm/s 和 mrad/s 编码。 */
void TestDrivePhysicalVelocity() {
  const auto raw = small_car::MakeDriveFrame(1, 600, -2000, 1);
  small_car::FrameParser parser;
  const auto frames = parser.Feed(raw);
  Expect(frames.size() == 1, "drive frame parse failed");
  const auto& payload = frames[0].payload;
  Expect(payload[6] == 0x58 && payload[7] == 0x02,
         "linear velocity encoding mismatch");
  Expect(payload[8] == 0x30 && payload[9] == 0xF8,
         "angular velocity encoding mismatch");
}

}  // namespace

int main() {
  try {
    TestCrc();
    TestEncodeParse();
    TestNoiseAndSplit();
    TestBadCrcDropped();
    TestDecodeChassis();
    TestDecodeEncoderCounts();
    TestParamSetGetFrame();
    TestDecodeParamValue();
    TestDrivePhysicalVelocity();
  } catch (const std::exception& error) {
    std::cerr << error.what() << "\n";
    return 1;
  }

  std::cout << "protocol_test passed\n";
  return 0;
}
