#include "agent_client/utterance_buffer.hpp"
#include "agent_client/voice_activity_detector.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>

#include "small_car_base/buffer/ring_buffer.hpp"

int main() {
  small_car::RingBuffer<std::uint8_t> preroll(8);
  const std::array<std::uint8_t, 4> initial = {1, 0, 2, 0};
  preroll.Write(initial.data(), initial.size());

  agent_client::UtteranceBuffer utterance(16000, 1, 1);
  utterance.Start(preroll);
  auto* writable = utterance.Writable(4);
  assert(writable != nullptr);
  const std::array<std::uint8_t, 4> samples = {0xff, 0x7f, 0x00, 0x80};
  std::memcpy(writable, samples.data(), samples.size());
  utterance.Commit(samples.size());
  auto wav = utterance.ReleaseWav();

  // vector 被直接移动给调用方，PCM 地址保持不变，没有复制完整语音。
  assert(wav.data() + 44 + initial.size() == writable);
  assert(wav.size() == 44 + initial.size() + samples.size());
  assert(std::memcmp(wav.data(), "RIFF", 4) == 0);
  assert(std::memcmp(wav.data() + 8, "WAVE", 4) == 0);
  assert(std::memcmp(wav.data() + 36, "data", 4) == 0);

  agent_client::VoiceActivityDetector vad(500);
  const std::array<std::uint8_t, 4> quiet = {1, 0, 1, 0};
  assert(!vad.IsSpeech(quiet.data(), quiet.size()));
  assert(vad.IsSpeech(samples.data(), samples.size()));
  return 0;
}
