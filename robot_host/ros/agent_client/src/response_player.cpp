#include "agent_client/response_player.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <stdexcept>
#include <utility>

#include "small_car_base/audio/audio_device.hpp"

namespace agent_client {
namespace {

std::uint16_t ReadU16(const std::uint8_t* input) {
  return static_cast<std::uint16_t>(input[0]) |
         (static_cast<std::uint16_t>(input[1]) << 8U);
}

std::uint32_t ReadU32(const std::uint8_t* input) {
  return static_cast<std::uint32_t>(input[0]) |
         (static_cast<std::uint32_t>(input[1]) << 8U) |
         (static_cast<std::uint32_t>(input[2]) << 16U) |
         (static_cast<std::uint32_t>(input[3]) << 24U);
}

struct WavView {
  std::uint32_t sample_rate = 0;
  std::uint16_t channels = 0;
  const std::uint8_t* pcm = nullptr;
  std::size_t pcm_bytes = 0;
};

WavView ParsePcm16Wav(const std::vector<std::uint8_t>& wav) {
  if (wav.size() < 44 || std::memcmp(wav.data(), "RIFF", 4) != 0 ||
      std::memcmp(wav.data() + 8, "WAVE", 4) != 0) {
    throw std::invalid_argument("Agent 返回的音频不是 WAV");
  }
  WavView view;
  std::uint16_t bits_per_sample = 0;
  std::size_t offset = 12;
  while (offset + 8 <= wav.size()) {
    const auto* chunk = wav.data() + offset;
    const std::uint32_t chunk_size = ReadU32(chunk + 4);
    const std::size_t data_offset = offset + 8;
    if (chunk_size > wav.size() - data_offset) {
      throw std::invalid_argument("WAV chunk 长度无效");
    }
    if (std::memcmp(chunk, "fmt ", 4) == 0) {
      if (chunk_size < 16 || ReadU16(wav.data() + data_offset) != 1) {
        throw std::invalid_argument("只支持未压缩 PCM WAV");
      }
      view.channels = ReadU16(wav.data() + data_offset + 2);
      view.sample_rate = ReadU32(wav.data() + data_offset + 4);
      bits_per_sample = ReadU16(wav.data() + data_offset + 14);
    } else if (std::memcmp(chunk, "data", 4) == 0) {
      view.pcm = wav.data() + data_offset;
      view.pcm_bytes = chunk_size;
    }
    offset = data_offset + chunk_size + (chunk_size & 1U);
  }
  if (view.sample_rate == 0 || view.channels == 0 || bits_per_sample != 16 ||
      view.pcm == nullptr || view.pcm_bytes == 0 ||
      view.pcm_bytes % (view.channels * 2U) != 0) {
    throw std::invalid_argument("WAV 必须包含有效的 16-bit PCM 数据");
  }
  return view;
}

}  // namespace

ResponsePlayer::ResponsePlayer(std::string device, ErrorHandler error_handler)
    : device_(std::move(device)), error_handler_(std::move(error_handler)) {}

ResponsePlayer::~ResponsePlayer() { Stop(); }

void ResponsePlayer::Play(std::vector<std::uint8_t> wav) {
  Stop();
  stop_requested_.store(false);
  playing_.store(true);
  thread_ = std::thread(&ResponsePlayer::Run, this, std::move(wav));
}

void ResponsePlayer::Stop() {
  stop_requested_.store(true);
  if (thread_.joinable()) {
    thread_.join();
  }
  playing_.store(false);
}

void ResponsePlayer::Run(std::vector<std::uint8_t> wav) {
  try {
    const WavView view = ParsePcm16Wav(wav);
    small_car::AudioConfig config;
    config.device = device_;
    config.sample_rate = view.sample_rate;
    config.channels = view.channels;
    config.period_frames = std::max<std::uint32_t>(1, view.sample_rate / 50U);
    small_car::AudioPlayback playback(config);
    const std::size_t bytes_per_frame = view.channels * 2U;
    const std::size_t period_bytes = config.period_frames * bytes_per_frame;
    std::size_t offset = 0;
    while (offset < view.pcm_bytes && !stop_requested_.load()) {
      const std::size_t byte_count =
          std::min(period_bytes, view.pcm_bytes - offset);
      playback.WriteBytes(view.pcm + offset, byte_count / bytes_per_frame);
      offset += byte_count;
    }
    if (stop_requested_.load()) {
      playback.Stop();
    } else {
      playback.Drain();
      // 暂停 VAD 直到房间混响尾音基本消失。
      std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
  } catch (const std::exception& error) {
    if (error_handler_) {
      error_handler_(error.what());
    }
  }
  playing_.store(false);
}

}  // namespace agent_client
