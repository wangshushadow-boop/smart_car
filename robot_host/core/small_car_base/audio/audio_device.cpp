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

  std::size_t completed = 0;
  while (completed < frame_count) {
    const auto remaining = static_cast<snd_pcm_uframes_t>(frame_count - completed);
    PcmSample* destination =
        samples + completed * static_cast<std::size_t>(impl_->config.channels);
    const snd_pcm_sframes_t result =
        snd_pcm_readi(impl_->handle, destination, remaining);
    if (result < 0) {
      RecoverPcm(impl_->handle, static_cast<int>(result), "snd_pcm_readi");
      continue;
    }
    completed += static_cast<std::size_t>(result);
  }
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

  std::size_t completed = 0;
  while (completed < frame_count) {
    const auto remaining = static_cast<snd_pcm_uframes_t>(frame_count - completed);
    const PcmSample* source =
        samples + completed * static_cast<std::size_t>(impl_->config.channels);
    const snd_pcm_sframes_t result =
        snd_pcm_writei(impl_->handle, source, remaining);
    if (result < 0) {
      RecoverPcm(impl_->handle, static_cast<int>(result), "snd_pcm_writei");
      continue;
    }
    completed += static_cast<std::size_t>(result);
  }
}

void AudioPlayback::Drain() {
  CheckAlsa(snd_pcm_drain(impl_->handle), "snd_pcm_drain");
}

const AudioConfig& AudioPlayback::config() const { return impl_->config; }

}  // namespace small_car
