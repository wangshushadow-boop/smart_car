#include "agent_client/agent_client_node.hpp"

#include <algorithm>
#include <chrono>
#include <exception>
#include <optional>
#include <stdexcept>
#include <utility>

#include <small_car_interfaces/msg/agent_content.hpp>

namespace agent_client {

AgentClientNode::AgentClientNode() : Node("car_agent_client") {
  capture_config_.device =
      declare_parameter<std::string>("audio_device", "plughw:CARD=USB,DEV=0");
  capture_config_.sample_rate =
      static_cast<std::uint32_t>(declare_parameter<int>("sample_rate", 16000));
  capture_config_.channels =
      static_cast<std::uint32_t>(declare_parameter<int>("channels", 1));
  capture_config_.period_frames = static_cast<std::uint32_t>(
      declare_parameter<int>("period_frames", 320));
  const auto energy_threshold = static_cast<std::uint32_t>(
      declare_parameter<int>("vad_energy_threshold", 500));
  const auto min_speech_ms = static_cast<std::uint64_t>(
      declare_parameter<int>("vad_min_speech_ms", 300));
  const auto silence_ms = static_cast<std::uint64_t>(
      declare_parameter<int>("vad_silence_ms", 600));
  const auto preroll_ms = static_cast<std::uint64_t>(
      declare_parameter<int>("vad_preroll_ms", 500));
  const auto max_speech_seconds = static_cast<std::uint32_t>(
      declare_parameter<int>("max_speech_seconds", 15));
  const std::string playback_device = declare_parameter<std::string>(
      "playback_device", capture_config_.device);
  const std::string image_topic =
      declare_parameter<std::string>("image_topic", "");
  const std::string action_name =
      declare_parameter<std::string>("agent_action", "");
  const std::string drive_action =
      declare_parameter<std::string>("nav_drive_action", "");
  const std::string spin_action =
      declare_parameter<std::string>("nav_spin_action", "");
  const double max_distance_m =
      declare_parameter<double>("motion_max_distance_m", 2.0);
  const double max_rotation_deg =
      declare_parameter<double>("motion_max_rotation_deg", 180.0);
  const double linear_speed_mps =
      declare_parameter<double>("motion_linear_speed_mps", 0.2);
  const double motion_timeout_seconds =
      declare_parameter<double>("motion_timeout_seconds", 15.0);
  if (capture_config_.channels != 1 || image_topic.empty() ||
      action_name.empty() || drive_action.empty() || spin_action.empty()) {
    throw std::invalid_argument(
        "Agent Client 需要单声道音频以及有效的 Agent、图像和 Nav2 接口");
  }

  const std::size_t bytes_per_frame = capture_config_.channels * 2U;
  const std::size_t period_bytes =
      capture_config_.period_frames * bytes_per_frame;
  const std::size_t preroll_bytes =
      static_cast<std::size_t>(capture_config_.sample_rate) * bytes_per_frame *
      preroll_ms / 1000U;
  idle_period_.resize(period_bytes);
  min_speech_ns_ = min_speech_ms * 1000000ULL;
  silence_limit_ns_ = silence_ms * 1000000ULL;
  vad_ = std::make_unique<VoiceActivityDetector>(energy_threshold);
  utterance_ = std::make_unique<UtteranceBuffer>(
      capture_config_.sample_rate,
      static_cast<std::uint16_t>(capture_config_.channels), max_speech_seconds);
  preroll_ = std::make_unique<small_car::RingBuffer<std::uint8_t>>(
      std::max<std::size_t>(period_bytes, preroll_bytes));
  player_ = std::make_unique<ResponsePlayer>(
      playback_device, [this](const std::string& error) {
        RCLCPP_ERROR(get_logger(), "播放 Agent 音频失败：%s", error.c_str());
      });
  action_client_ = std::make_unique<AgentActionClient>(
      this, action_name,
      [this](AgentActionClient::Response response) {
        HandleResponse(std::move(response));
      },
      [this](const std::string& message) { HandleActionFailure(message); });
  motion_parser_ = std::make_unique<MotionTaskParser>(
      MotionLimits{max_distance_m, max_rotation_deg});
  nav2_client_ = std::make_unique<Nav2MotionClient>(
      this, drive_action, spin_action, linear_speed_mps, motion_timeout_seconds,
      [this](const std::string& event) {
        RCLCPP_INFO(get_logger(), "运动任务：%s", event.c_str());
      });

  image_subscription_ = create_subscription<sensor_msgs::msg::CompressedImage>(
      image_topic, rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::CompressedImage::UniquePtr message) {
        camera_.Store(std::move(message));
      });
  session_id_ = "pi-" + std::to_string(now().nanoseconds());
  capture_thread_ = std::thread(&AgentClientNode::CaptureLoop, this);
  RCLCPP_INFO(get_logger(), "C++ Agent Client 已启动：%s", action_name.c_str());
}

AgentClientNode::~AgentClientNode() {
  stopping_.store(true);
  action_client_->Cancel();
  nav2_client_->Stop();
  player_->Stop();
  if (capture_thread_.joinable()) {
    capture_thread_.join();
  }
}

void AgentClientNode::CaptureLoop() {
  const std::size_t bytes_per_frame = capture_config_.channels * 2U;
  const std::size_t period_bytes =
      capture_config_.period_frames * bytes_per_frame;
  const std::uint64_t period_ns =
      static_cast<std::uint64_t>(capture_config_.period_frames) * 1000000000ULL /
      capture_config_.sample_rate;

  while (!stopping_.load()) {
    try {
      small_car::AudioCapture capture(capture_config_);
      while (!stopping_.load()) {
        if (player_->playing() || request_active_.load()) {
          capture.ReadBytes(idle_period_.data(), capture_config_.period_frames);
          ResetSpeechState();
          continue;
        }

        if (!utterance_->active()) {
          capture.ReadBytes(idle_period_.data(), capture_config_.period_frames);
          const bool voiced = vad_->IsSpeech(idle_period_.data(), period_bytes);
          preroll_->Write(idle_period_.data(), period_bytes);
          if (voiced) {
            utterance_->Start(*preroll_);
            preroll_->Clear();
            speech_ns_ = period_ns;
            silence_ns_ = 0;
          }
          continue;
        }

        auto* destination = utterance_->Writable(period_bytes);
        if (destination == nullptr) {
          FinishUtterance();
          continue;
        }
        capture.ReadBytes(destination, capture_config_.period_frames);
        const bool voiced = vad_->IsSpeech(destination, period_bytes);
        utterance_->Commit(period_bytes);
        if (voiced) {
          speech_ns_ += period_ns;
          silence_ns_ = 0;
        } else {
          silence_ns_ += period_ns;
        }
        if (silence_ns_ >= silence_limit_ns_ || utterance_->full()) {
          FinishUtterance();
        }
      }
    } catch (const std::exception& error) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000,
                            "音频采集失败，准备重连：%s", error.what());
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
}

void AgentClientNode::ResetSpeechState() {
  utterance_->Reset();
  preroll_->Clear();
  speech_ns_ = 0;
  silence_ns_ = 0;
}

void AgentClientNode::FinishUtterance() {
  if (!utterance_->active() || speech_ns_ < min_speech_ns_) {
    ResetSpeechState();
    return;
  }
  auto wav = utterance_->ReleaseWav();
  auto jpeg = camera_.TakeLatest();
  speech_ns_ = 0;
  silence_ns_ = 0;
  preroll_->Clear();
  request_active_.store(true);
  const std::string request_id = NextRequestId();
  if (!action_client_->Send(request_id, session_id_, std::move(wav),
                            std::move(jpeg))) {
    request_active_.store(false);
  } else {
    RCLCPP_INFO(get_logger(), "已提交多模态请求：%s",
                request_id.substr(0, 16).c_str());
  }
}

void AgentClientNode::HandleResponse(AgentActionClient::Response response) {
  std::vector<std::uint8_t> answer_audio;
  std::optional<MotionTask> motion_task;
  bool invalid_motion_task = false;
  for (auto& output : response.outputs) {
    if (output.content_type == small_car_interfaces::msg::AgentContent::TEXT) {
      RCLCPP_INFO(get_logger(), "Agent：%s", output.text.c_str());
    } else if (output.content_type ==
                   small_car_interfaces::msg::AgentContent::AUDIO &&
               !output.data.empty()) {
      answer_audio = std::move(output.data);
    } else if (output.content_type ==
                   small_car_interfaces::msg::AgentContent::JSON &&
               output.name == "robot_task") {
      std::string error;
      auto parsed = motion_parser_->Parse(output.text, &error);
      if (!parsed || motion_task) {
        invalid_motion_task = true;
        RCLCPP_ERROR(get_logger(), "Agent 运动任务已拒绝：%s",
                     parsed ? "响应包含多个运动任务" : error.c_str());
      } else {
        motion_task = *parsed;
      }
    }
  }
  if (!response.error_message.empty()) {
    RCLCPP_WARN(get_logger(), "Agent 部分失败：%s",
                response.error_message.c_str());
  }
  // 运动时不播放确认语音，避免扬声器占用和车辆启动同时发生。
  if (!invalid_motion_task && motion_task) {
    nav2_client_->Execute(*motion_task);
  } else if (!answer_audio.empty() && !invalid_motion_task) {
    player_->Play(std::move(answer_audio));
  }
  request_active_.store(false);
}

void AgentClientNode::HandleActionFailure(const std::string& message) {
  request_active_.store(false);
  RCLCPP_ERROR(get_logger(), "%s", message.c_str());
}

std::string AgentClientNode::NextRequestId() {
  return "pi-" + std::to_string(now().nanoseconds()) + "-" +
         std::to_string(request_sequence_.fetch_add(1));
}

}  // namespace agent_client
