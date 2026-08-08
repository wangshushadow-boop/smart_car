#include <cerrno>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <csignal>
#include <cstring>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <utility>
#include <vector>

#include <rclcpp/rclcpp.hpp>

#include "small_car_interfaces/msg/audio_frame.hpp"

namespace small_car_av {
namespace {

class AplayProcess {
 public:
  explicit AplayProcess(std::string device) : device_(std::move(device)) {}
  ~AplayProcess() { Stop(); }

  bool EnsureFormat(std::uint32_t sample_rate, std::uint8_t channels) {
    if (write_fd_ >= 0 && sample_rate_ == sample_rate && channels_ == channels) {
      return true;
    }
    Stop();
    return Start(sample_rate, channels);
  }

  bool Write(const std::uint8_t* data, std::size_t size) {
    while (size > 0) {
      const ssize_t written = ::write(write_fd_, data, size);
      if (written > 0) {
        data += written;
        size -= static_cast<std::size_t>(written);
        continue;
      }
      if (written < 0 && errno == EINTR) {
        continue;
      }
      Stop();
      return false;
    }
    return true;
  }

 private:
  bool Start(std::uint32_t sample_rate, std::uint8_t channels) {
    int pipe_fds[2] = {-1, -1};
    if (::pipe(pipe_fds) != 0) {
      return false;
    }
    const pid_t child = ::fork();
    if (child == 0) {
      ::dup2(pipe_fds[0], STDIN_FILENO);
      ::close(pipe_fds[0]);
      ::close(pipe_fds[1]);
      const std::string rate = std::to_string(sample_rate);
      const std::string channel_count = std::to_string(channels);
      ::execlp("aplay", "aplay", "--quiet", "--device", device_.c_str(), "--format", "S16_LE",
               "--rate", rate.c_str(), "--channels", channel_count.c_str(), "--file-type", "raw",
               static_cast<char*>(nullptr));
      _exit(127);
    }
    ::close(pipe_fds[0]);
    if (child < 0) {
      ::close(pipe_fds[1]);
      return false;
    }
    child_pid_ = child;
    write_fd_ = pipe_fds[1];
    sample_rate_ = sample_rate;
    channels_ = channels;
    return true;
  }

  void Stop() {
    if (write_fd_ >= 0) {
      ::close(write_fd_);
      write_fd_ = -1;
    }
    if (child_pid_ > 0) {
      int status = 0;
      if (::waitpid(child_pid_, &status, WNOHANG) == 0) {
        ::kill(child_pid_, SIGTERM);
        ::waitpid(child_pid_, &status, 0);
      }
      child_pid_ = -1;
    }
    sample_rate_ = 0;
    channels_ = 0;
  }

  std::string device_;
  pid_t child_pid_ = -1;
  int write_fd_ = -1;
  std::uint32_t sample_rate_ = 0;
  std::uint8_t channels_ = 0;
};

struct AudioPacket {
  std::uint32_t sample_rate = 0;
  std::uint8_t channels = 0;
  std::vector<std::uint8_t> data;
};

}  // namespace

class JabraAudioPlayer : public rclcpp::Node {
 public:
  JabraAudioPlayer() : Node("small_car_jabra_audio_player") {
    device_ = declare_parameter<std::string>("alsa_device", "plughw:CARD=USB,DEV=0");
    topic_ = declare_parameter<std::string>("output_topic", "");
    if (topic_.empty()) {
      throw std::invalid_argument("output_topic must be provided by the interface contract");
    }
    auto qos = rclcpp::QoS(rclcpp::KeepLast(100)).reliable();
    subscription_ = create_subscription<small_car_interfaces::msg::AudioFrame>(
        topic_, qos, std::bind(&JabraAudioPlayer::Enqueue, this, std::placeholders::_1));
    writer_thread_ = std::thread(&JabraAudioPlayer::WriterLoop, this);
    RCLCPP_INFO(get_logger(), "audio output uses aplay pipe: %s", device_.c_str());
  }

  ~JabraAudioPlayer() override {
    {
      std::lock_guard<std::mutex> lock(queue_mutex_);
      stopping_ = true;
    }
    queue_ready_.notify_all();
    if (writer_thread_.joinable()) {
      writer_thread_.join();
    }
  }

 private:
  void Enqueue(const small_car_interfaces::msg::AudioFrame::SharedPtr message) {
    const std::size_t expected_bytes = static_cast<std::size_t>(message->frame_samples) *
                                       message->channels * sizeof(std::int16_t);
    if (message->encoding != "pcm_s16le" || message->sample_rate == 0 ||
        message->channels == 0 || message->frame_samples == 0 ||
        message->data.empty() || message->data.size() != expected_bytes) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "discarding invalid audio frame");
      return;
    }
    std::lock_guard<std::mutex> lock(queue_mutex_);
    if (queue_.size() >= 100) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "discarding audio frame because aplay queue is full");
      return;
    }
    queue_.push_back({message->sample_rate, message->channels,
                      std::vector<std::uint8_t>(message->data.begin(), message->data.end())});
    queue_ready_.notify_one();
  }

  void WriterLoop() {
    AplayProcess aplay(device_);
    while (true) {
      AudioPacket packet;
      {
        std::unique_lock<std::mutex> lock(queue_mutex_);
        queue_ready_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
        if (stopping_) {
          return;
        }
        packet = std::move(queue_.front());
        queue_.pop_front();
      }
      if (!aplay.EnsureFormat(packet.sample_rate, packet.channels) ||
          !aplay.Write(packet.data.data(), packet.data.size())) {
        RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000,
                              "aplay pipe write failed; restarting playback process");
        if (aplay.EnsureFormat(packet.sample_rate, packet.channels)) {
          aplay.Write(packet.data.data(), packet.data.size());
        }
      }
    }
  }

  std::string device_;
  std::string topic_;
  std::deque<AudioPacket> queue_;
  bool stopping_ = false;
  std::mutex queue_mutex_;
  std::condition_variable queue_ready_;
  std::thread writer_thread_;
  rclcpp::Subscription<small_car_interfaces::msg::AudioFrame>::SharedPtr subscription_;
};

}  // namespace small_car_av

int main(int argc, char** argv) {
  std::signal(SIGPIPE, SIG_IGN);
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<small_car_av::JabraAudioPlayer>());
  rclcpp::shutdown();
  return 0;
}
