/**
 * @file audio_device.cpp
 * @brief ALSA-backed streaming PCM capture and playback implementation.
 */
#include "small_car_base/audio/audio_device.hpp"

#include <alsa/asoundlib.h>

#include <algorithm>
#include <stdexcept>
#include <string>
#include <utility>

namespace small_car {
namespace {

void CheckAlsa(int result, const char* operation) {
  if (result < 0) {
    throw std::runtime_error(std::string(operation) + ": " +
                             snd_strerror(result));
  }
}

void ValidateConfig(const AudioConfig& config) {
  if (config.device.empty() || config.sample_rate == 0 ||
      config.channels == 0 || config.period_frames == 0) {
    throw std::invalid_argument("audio configuration contains a zero value");
  }
}

snd_pcm_t* OpenPcm(const AudioConfig& config, snd_pcm_stream_t stream) {
  ValidateConfig(config);
  snd_pcm_t* handle = nullptr;
  CheckAlsa(snd_pcm_open(&handle, config.device.c_str(), stream, 0),
            "snd_pcm_open");

  try {
    snd_pcm_hw_params_t* params = nullptr;
    snd_pcm_hw_params_alloca(&params);
    CheckAlsa(snd_pcm_hw_params_any(handle, params),
              "snd_pcm_hw_params_any");
    CheckAlsa(snd_pcm_hw_params_set_access(
                  handle, params, SND_PCM_ACCESS_RW_INTERLEAVED),
              "snd_pcm_hw_params_set_access");
    CheckAlsa(snd_pcm_hw_params_set_format(handle, params,
                                            SND_PCM_FORMAT_S16_LE),
              "snd_pcm_hw_params_set_format");
    CheckAlsa(snd_pcm_hw_params_set_channels(handle, params, config.channels),
              "snd_pcm_hw_params_set_channels");

    unsigned int rate = config.sample_rate;
    CheckAlsa(snd_pcm_hw_params_set_rate_near(handle, params, &rate, nullptr),
              "snd_pcm_hw_params_set_rate_near");
    if (rate != config.sample_rate) {
      throw std::runtime_error("ALSA device does not support requested rate");
    }

    snd_pcm_uframes_t period = config.period_frames;
    CheckAlsa(snd_pcm_hw_params_set_period_size_near(handle, params, &period,
                                                      nullptr),
              "snd_pcm_hw_params_set_period_size_near");
    CheckAlsa(snd_pcm_hw_params(handle, params), "snd_pcm_hw_params");
    CheckAlsa(snd_pcm_prepare(handle), "snd_pcm_prepare");
  } catch (...) {
    snd_pcm_close(handle);
    throw;
  }
  return handle;
}

void RecoverPcm(snd_pcm_t* handle, int result, const char* operation) {
  CheckAlsa(snd_pcm_recover(handle, result, 1), operation);
}

void ReadInterleaved(snd_pcm_t* handle, const AudioConfig& config,
                     std::uint8_t* data, std::size_t frame_count) {
  std::size_t completed = 0;
  const std::size_t bytes_per_frame =
      static_cast<std::size_t>(config.channels) * sizeof(PcmSample);
  while (completed < frame_count) {
    const auto remaining =
        static_cast<snd_pcm_uframes_t>(frame_count - completed);
    const snd_pcm_sframes_t result =
        snd_pcm_readi(handle, data + completed * bytes_per_frame, remaining);
    if (result < 0) {
      RecoverPcm(handle, static_cast<int>(result), "snd_pcm_readi");
      continue;
    }
    completed += static_cast<std::size_t>(result);
  }
}

void WriteInterleaved(snd_pcm_t* handle, const AudioConfig& config,
                      const std::uint8_t* data, std::size_t frame_count) {
  std::size_t completed = 0;
  const std::size_t bytes_per_frame =
      static_cast<std::size_t>(config.channels) * sizeof(PcmSample);
  while (completed < frame_count) {
    const auto remaining =
        static_cast<snd_pcm_uframes_t>(frame_count - completed);
    const snd_pcm_sframes_t result =
        snd_pcm_writei(handle, data + completed * bytes_per_frame, remaining);
    if (result < 0) {
      RecoverPcm(handle, static_cast<int>(result), "snd_pcm_writei");
      continue;
    }
    completed += static_cast<std::size_t>(result);
  }
}

}  // namespace

class AudioCapture::Impl {
 public:
  explicit Impl(AudioConfig value)
      : config(std::move(value)), handle(OpenPcm(config, SND_PCM_STREAM_CAPTURE)) {}

  ~Impl() { snd_pcm_close(handle); }

  AudioConfig config;
  snd_pcm_t* handle;
};

AudioCapture::AudioCapture(AudioConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}
AudioCapture::~AudioCapture() = default;
AudioCapture::AudioCapture(AudioCapture&&) noexcept = default;
AudioCapture& AudioCapture::operator=(AudioCapture&&) noexcept = default;

void AudioCapture::ReadFrames(PcmSample* samples, std::size_t frame_count) {
  if (samples == nullptr && frame_count != 0) {
    throw std::invalid_argument("capture destination is null");
  }

  ReadInterleaved(impl_->handle, impl_->config,
                  reinterpret_cast<std::uint8_t*>(samples), frame_count);
}

void AudioCapture::ReadBytes(std::uint8_t* data, std::size_t frame_count) {
  if (data == nullptr && frame_count != 0) {
    throw std::invalid_argument("capture byte destination is null");
  }
  ReadInterleaved(impl_->handle, impl_->config, data, frame_count);
}

const AudioConfig& AudioCapture::config() const { return impl_->config; }

class AudioPlayback::Impl {
 public:
  explicit Impl(AudioConfig value)
      : config(std::move(value)), handle(OpenPcm(config, SND_PCM_STREAM_PLAYBACK)) {}

  ~Impl() { snd_pcm_close(handle); }

  AudioConfig config;
  snd_pcm_t* handle;
};

AudioPlayback::AudioPlayback(AudioConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}
AudioPlayback::~AudioPlayback() = default;
AudioPlayback::AudioPlayback(AudioPlayback&&) noexcept = default;
AudioPlayback& AudioPlayback::operator=(AudioPlayback&&) noexcept = default;

void AudioPlayback::WriteFrames(const PcmSample* samples,
                                std::size_t frame_count) {
  if (samples == nullptr && frame_count != 0) {
    throw std::invalid_argument("playback source is null");
  }

  WriteInterleaved(impl_->handle, impl_->config,
                   reinterpret_cast<const std::uint8_t*>(samples), frame_count);
}

void AudioPlayback::WriteBytes(const std::uint8_t* data,
                               std::size_t frame_count) {
  if (data == nullptr && frame_count != 0) {
    throw std::invalid_argument("playback byte source is null");
  }
  WriteInterleaved(impl_->handle, impl_->config, data, frame_count);
}

void AudioPlayback::Stop() {
  CheckAlsa(snd_pcm_drop(impl_->handle), "snd_pcm_drop");
  CheckAlsa(snd_pcm_prepare(impl_->handle), "snd_pcm_prepare");
}

void AudioPlayback::Drain() {
  CheckAlsa(snd_pcm_drain(impl_->handle), "snd_pcm_drain");
}

const AudioConfig& AudioPlayback::config() const { return impl_->config; }

}  // namespace small_car
