/** @file utterance_buffer.hpp @brief 单轮语音使用的连续、可移动 WAV 工作缓冲。 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "small_car_base/buffer/ring_buffer.hpp"

namespace agent_client {

class UtteranceBuffer {
 public:
  UtteranceBuffer(std::uint32_t sample_rate, std::uint16_t channels,
                  std::uint32_t max_seconds);

  UtteranceBuffer(const UtteranceBuffer&) = delete;
  UtteranceBuffer& operator=(const UtteranceBuffer&) = delete;

  void Start(const small_car::RingBuffer<std::uint8_t>& preroll);
  std::uint8_t* Writable(std::size_t requested_bytes);
  void Commit(std::size_t byte_count);
  bool active() const { return active_; }
  bool full(std::size_t next_bytes = 0) const;
  std::size_t pcm_bytes() const { return pcm_bytes_; }
  void Reset();

  /** 原地写入 WAV Header，并移动底层 vector，不复制完整语音。 */
  std::vector<std::uint8_t> ReleaseWav();

 private:
  void EnsureStorage();

  static constexpr std::size_t kWavHeaderBytes = 44;
  std::uint32_t sample_rate_;
  std::uint16_t channels_;
  std::size_t max_pcm_bytes_;
  std::vector<std::uint8_t> storage_;
  std::size_t pcm_bytes_ = 0;
  bool active_ = false;
};

}  // namespace agent_client
