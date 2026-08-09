/**
 * @file audio_device.hpp
 * @brief ROS-independent streaming PCM capture and playback interfaces.
 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace small_car {

using PcmSample = std::int16_t;

struct AudioConfig {
  std::string device = "plughw:0,0";
  std::uint32_t sample_rate = 16000;
  std::uint32_t channels = 1;
  std::uint32_t period_frames = 320;
};

/** Keeps one ALSA capture stream open and reads interleaved S16_LE frames. */
class AudioCapture {
 public:
  explicit AudioCapture(AudioConfig config);
  ~AudioCapture();

  AudioCapture(const AudioCapture&) = delete;
  AudioCapture& operator=(const AudioCapture&) = delete;
  AudioCapture(AudioCapture&&) noexcept;
  AudioCapture& operator=(AudioCapture&&) noexcept;

  /** Blocks until frame_count frames have been captured. */
  void ReadFrames(PcmSample* samples, std::size_t frame_count);
  /** 直接写入调用方提供的 PCM 字节区，避免中间大型 vector。 */
  void ReadBytes(std::uint8_t* data, std::size_t frame_count);
  const AudioConfig& config() const;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

/** Keeps one ALSA playback stream open and writes interleaved S16_LE frames. */
class AudioPlayback {
 public:
  explicit AudioPlayback(AudioConfig config);
  ~AudioPlayback();

  AudioPlayback(const AudioPlayback&) = delete;
  AudioPlayback& operator=(const AudioPlayback&) = delete;
  AudioPlayback(AudioPlayback&&) noexcept;
  AudioPlayback& operator=(AudioPlayback&&) noexcept;

  /** Blocks until frame_count frames have been accepted by ALSA. */
  void WriteFrames(const PcmSample* samples, std::size_t frame_count);
  /** 直接播放调用方持有的 PCM 字节区，不接管其所有权。 */
  void WriteBytes(const std::uint8_t* data, std::size_t frame_count);
  /** 立即丢弃尚未播放的数据，用于取消或用户打断。 */
  void Stop();
  void Drain();
  const AudioConfig& config() const;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace small_car
