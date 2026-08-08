#include <cstddef>
#include <cstdint>
#include <cstring>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <rclcpp/rclcpp.hpp>

#include "small_car_base/audio/audio_device.hpp"
#include "small_car_interfaces/msg/audio_frame.hpp"

namespace small_car_av {

class JabraAudioPlayer : public rclcpp::Node {
 public:
  JabraAudioPlayer() : Node("small_car_jabra_audio_player") {
    device_ = declare_parameter<std::string>(
        "alsa_device", "plughw:CARD=USB,DEV=0");
    auto qos = rclcpp::QoS(rclcpp::KeepLast(100)).reliable();
    subscription_ = create_subscription<small_car_interfaces::msg::AudioFrame>(
        "/car/audio/output", qos,
        std::bind(&JabraAudioPlayer::Play, this, std::placeholders::_1));
    RCLCPP_INFO(get_logger(), "waiting for audio output on ALSA %s",
                device_.c_str());
  }

 private:
  void Play(const small_car_interfaces::msg::AudioFrame::SharedPtr message) {
    if (message->encoding != "pcm_s16le" || message->data.empty() ||
        message->sample_rate == 0 || message->channels == 0 ||
        message->frame_samples == 0) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "discarding invalid audio output frame");
      return;
    }

    const std::size_t expected_bytes =
        static_cast<std::size_t>(message->frame_samples) * message->channels *
        sizeof(small_car::PcmSample);
    if (message->data.size() != expected_bytes) {
      RCLCPP_WARN_THROTTLE(
          get_logger(), *get_clock(), 5000,
          "audio output size mismatch: received %zu, expected %zu",
          message->data.size(), expected_bytes);
      return;
    }

    try {
      EnsurePlayback(message->sample_rate, message->channels,
                     message->frame_samples);
      samples_.resize(expected_bytes / sizeof(small_car::PcmSample));
      std::memcpy(samples_.data(), message->data.data(), expected_bytes);
      playback_->WriteFrames(samples_.data(), message->frame_samples);
    } catch (const std::exception& error) {
      playback_.reset();
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000,
                            "audio playback failed: %s", error.what());
    }
  }

  void EnsurePlayback(std::uint32_t sample_rate, std::uint8_t channels,
                      std::uint32_t period_frames) {
    if (playback_ && active_sample_rate_ == sample_rate &&
        active_channels_ == channels) {
      return;
    }

    small_car::AudioConfig config;
    config.device = device_;
    config.sample_rate = sample_rate;
    config.channels = channels;
    config.period_frames = period_frames;
    playback_ = std::make_unique<small_car::AudioPlayback>(std::move(config));
    active_sample_rate_ = sample_rate;
    active_channels_ = channels;
  }

  std::string device_;
  std::uint32_t active_sample_rate_ = 0;
  std::uint8_t active_channels_ = 0;
  std::unique_ptr<small_car::AudioPlayback> playback_;
  std::vector<small_car::PcmSample> samples_;
  rclcpp::Subscription<small_car_interfaces::msg::AudioFrame>::SharedPtr
      subscription_;
};

}  // namespace small_car_av

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<small_car_av::JabraAudioPlayer>());
  rclcpp::shutdown();
  return 0;
}
