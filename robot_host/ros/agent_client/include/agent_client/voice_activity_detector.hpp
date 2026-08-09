/** @file voice_activity_detector.hpp @brief 无内存所有权的 PCM 能量 VAD。 */
#pragma once

#include <cstddef>
#include <cstdint>

namespace agent_client {

class VoiceActivityDetector {
 public:
  explicit VoiceActivityDetector(std::uint32_t energy_threshold);

  /** 输入必须是小端 PCM S16LE；函数只读取调用方缓冲。 */
  bool IsSpeech(const std::uint8_t* pcm, std::size_t byte_count) const;

 private:
  std::uint32_t energy_threshold_;
};

}  // namespace agent_client
