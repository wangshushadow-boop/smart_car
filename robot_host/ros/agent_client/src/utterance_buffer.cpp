#include "agent_client/utterance_buffer.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace agent_client {
namespace {

void WriteU16(std::uint8_t* output, std::uint16_t value) {
  output[0] = static_cast<std::uint8_t>(value & 0xffU);
  output[1] = static_cast<std::uint8_t>((value >> 8U) & 0xffU);
}

void WriteU32(std::uint8_t* output, std::uint32_t value) {
  for (std::size_t index = 0; index < 4; ++index) {
    output[index] = static_cast<std::uint8_t>((value >> (index * 8U)) & 0xffU);
  }
}

}  // namespace

UtteranceBuffer::UtteranceBuffer(std::uint32_t sample_rate,
                                 std::uint16_t channels,
                                 std::uint32_t max_seconds)
    : sample_rate_(sample_rate),
      channels_(channels),
      max_pcm_bytes_(static_cast<std::size_t>(sample_rate) * channels * 2U *
                     max_seconds) {
  if (sample_rate == 0 || channels == 0 || max_seconds == 0) {
    throw std::invalid_argument("utterance buffer configuration is invalid");
  }
  EnsureStorage();
}

void UtteranceBuffer::EnsureStorage() {
  if (storage_.capacity() < kWavHeaderBytes + max_pcm_bytes_) {
    storage_.reserve(kWavHeaderBytes + max_pcm_bytes_);
  }
  storage_.resize(kWavHeaderBytes + max_pcm_bytes_);
}

void UtteranceBuffer::Start(
    const small_car::RingBuffer<std::uint8_t>& preroll) {
  Reset();
  const std::size_t copied = std::min(preroll.size(), max_pcm_bytes_);
  preroll.CopyTo(storage_.data() + kWavHeaderBytes, copied);
  pcm_bytes_ = copied;
  active_ = true;
}

std::uint8_t* UtteranceBuffer::Writable(std::size_t requested_bytes) {
  if (!active_ || full(requested_bytes)) {
    return nullptr;
  }
  return storage_.data() + kWavHeaderBytes + pcm_bytes_;
}

void UtteranceBuffer::Commit(std::size_t byte_count) {
  if (!active_ || full(byte_count)) {
    throw std::out_of_range("utterance buffer commit exceeds capacity");
  }
  pcm_bytes_ += byte_count;
}

bool UtteranceBuffer::full(std::size_t next_bytes) const {
  if (next_bytes == 0) {
    return pcm_bytes_ >= max_pcm_bytes_;
  }
  return next_bytes > max_pcm_bytes_ - pcm_bytes_;
}

void UtteranceBuffer::Reset() {
  EnsureStorage();
  pcm_bytes_ = 0;
  active_ = false;
}

std::vector<std::uint8_t> UtteranceBuffer::ReleaseWav() {
  if (!active_ || pcm_bytes_ == 0 || pcm_bytes_ > 0xffffffffU - 36U) {
    throw std::runtime_error("cannot release an empty or oversized utterance");
  }
  auto* header = storage_.data();
  std::copy_n(reinterpret_cast<const std::uint8_t*>("RIFF"), 4, header);
  WriteU32(header + 4, static_cast<std::uint32_t>(36 + pcm_bytes_));
  std::copy_n(reinterpret_cast<const std::uint8_t*>("WAVEfmt "), 8, header + 8);
  WriteU32(header + 16, 16);
  WriteU16(header + 20, 1);
  WriteU16(header + 22, channels_);
  WriteU32(header + 24, sample_rate_);
  WriteU32(header + 28, sample_rate_ * channels_ * 2U);
  WriteU16(header + 32, static_cast<std::uint16_t>(channels_ * 2U));
  WriteU16(header + 34, 16);
  std::copy_n(reinterpret_cast<const std::uint8_t*>("data"), 4, header + 36);
  WriteU32(header + 40, static_cast<std::uint32_t>(pcm_bytes_));
  storage_.resize(kWavHeaderBytes + pcm_bytes_);
  active_ = false;
  pcm_bytes_ = 0;
  return std::move(storage_);
}

}  // namespace agent_client
