#include <chrono>
#include <cstdint>
#include <cstring>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>

#include "small_car_base/audio/audio_device.hpp"
#include "small_car_interfaces/msg/audio_frame.hpp"

namespace small_car_av {

class JabraAudioPublisher : public rclcpp::Node {
 public:
  JabraAudioPublisher() : Node("small_car_jabra_audio_publisher") {
    config_.device = declare_parameter<std::string>(
        "alsa_device", "plughw:CARD=USB,DEV=0");
    topic_ = declare_parameter<std::string>("input_topic", "");
    if (topic_.empty()) {
      throw std::invalid_argument("input_topic must be provided by the interface contract");
    }
    config_.sample_rate = static_cast<std::uint32_t>(
        declare_parameter<int>("sample_rate", 16000));
    config_.channels = static_cast<std::uint32_t>(
        declare_parameter<int>("channels", 1));
    config_.period_frames = static_cast<std::uint32_t>(
        declare_parameter<int>("frame_samples", 320));
    if (config_.sample_rate == 0 || config_.channels == 0 ||
        config_.period_frames == 0 || config_.channels > 255) {
      throw std::invalid_argument("invalid audio capture parameters");
    }

    samples_.resize(static_cast<std::size_t>(config_.period_frames) *
                    config_.channels);
    publisher_ = create_publisher<small_car_interfaces::msg::AudioFrame>(
        topic_, rclcpp::SensorDataQoS());
    timer_ = create_wall_timer(std::chrono::milliseconds(1),
                               std::bind(&JabraAudioPublisher::Capture, this));
    RCLCPP_INFO(get_logger(),
                "audio capture ready: %s, %u Hz, %u channel(s), %u frames",
                config_.device.c_str(), config_.sample_rate, config_.channels,
                config_.period_frames);
  }

 private:
  void Capture() {
    try {
      if (!capture_) {
        capture_ = std::make_unique<small_car::AudioCapture>(config_);
      }
      capture_->ReadFrames(samples_.data(), config_.period_frames);

      small_car_interfaces::msg::AudioFrame message;
      const std::int64_t frame_duration_ns =
          static_cast<std::int64_t>(config_.period_frames) * 1000000000LL /
          config_.sample_rate;
      message.header.stamp = now() - rclcpp::Duration::from_nanoseconds(
                                         frame_duration_ns);
      message.header.frame_id = "jabra_microphone";
      message.sample_rate = config_.sample_rate;
      message.channels = static_cast<std::uint8_t>(config_.channels);
      message.encoding = "pcm_s16le";
      message.frame_samples = config_.period_frames;
      message.data.resize(samples_.size() * sizeof(small_car::PcmSample));
      std::memcpy(message.data.data(), samples_.data(), message.data.size());
      publisher_->publish(std::move(message));
    } catch (const std::exception& error) {
      capture_.reset();
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000,
                            "audio capture failed: %s", error.what());
    }
  }

  small_car::AudioConfig config_;
  std::string topic_;
  std::unique_ptr<small_car::AudioCapture> capture_;
  std::vector<small_car::PcmSample> samples_;
  rclcpp::Publisher<small_car_interfaces::msg::AudioFrame>::SharedPtr publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}  // namespace small_car_av

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<small_car_av::JabraAudioPublisher>());
  rclcpp::shutdown();
  return 0;
}
