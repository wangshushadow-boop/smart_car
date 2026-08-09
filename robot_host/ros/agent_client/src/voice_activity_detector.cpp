#include "agent_client/voice_activity_detector.hpp"

#include <cmath>
#include <stdexcept>

namespace agent_client {

VoiceActivityDetector::VoiceActivityDetector(std::uint32_t energy_threshold)
    : energy_threshold_(energy_threshold) {
  if (energy_threshold == 0) {
    throw std::invalid_argument("VAD energy threshold must be positive");
  }
}

bool VoiceActivityDetector::IsSpeech(const std::uint8_t* pcm,
                                     std::size_t byte_count) const {
  if (pcm == nullptr || byte_count < 2 || byte_count % 2 != 0) {
    return false;
  }
  long double square_sum = 0.0;
  const std::size_t sample_count = byte_count / 2;
  for (std::size_t index = 0; index < sample_count; ++index) {
    const std::uint16_t raw = static_cast<std::uint16_t>(pcm[index * 2]) |
                              (static_cast<std::uint16_t>(pcm[index * 2 + 1]) << 8U);
    const auto sample = static_cast<std::int16_t>(raw);
    square_sum += static_cast<long double>(sample) * sample;
  }
  const auto rms = static_cast<std::uint32_t>(
      std::sqrt(square_sum / static_cast<long double>(sample_count)));
  return rms >= energy_threshold_;
}

}  // namespace agent_client
