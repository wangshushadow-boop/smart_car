#include "agent_client/agent_client_node.hpp"

#include <algorithm>
#include <chrono>
#include <exception>
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
  const std::string audio_service_name =
      declare_parameter<std::string>("audio_service", "");
  const auto max_playback_bytes =
      declare_parameter<int>("max_playback_bytes", 8 * 1024 * 1024);
  const double agent_request_timeout_seconds =
      declare_parameter<double>("agent_request_timeout_seconds", 360.0);
  if (agent_request_timeout_seconds <= 0.0) {
    throw std::invalid_argument("Agent 请求超时必须大于 0 秒");
  }
  request_timeout_ = std::chrono::milliseconds(static_cast<std::int64_t>(
      agent_request_timeout_seconds * 1000.0));
  if (capture_config_.channels != 1 || image_topic.empty() ||
      action_name.empty() || audio_service_name.empty() ||
      max_playback_bytes <= 0) {
    throw std::invalid_argument(
        "Agent Client 需要单声道音频以及有效的 Agent、图像和播放接口");
  }
  max_playback_bytes_ = static_cast<std::size_t>(max_playback_bytes);

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
      [this](const std::string& request_id,
             AgentActionClient::Response response) {
        HandleResponse(request_id, std::move(response));
      },
      [this](const std::string& request_id, const std::string& message) {
        HandleActionFailure(request_id, message);
      });
  image_subscription_ = create_subscription<sensor_msgs::msg::CompressedImage>(
      image_topic, rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::CompressedImage::UniquePtr message) {
        camera_.Store(std::move(message));
      });
  audio_service_ = create_service<small_car_interfaces::srv::PlayAudio>(
      audio_service_name,
      [this](
          const std::shared_ptr<small_car_interfaces::srv::PlayAudio::Request>
              request,
          std::shared_ptr<small_car_interfaces::srv::PlayAudio::Response>
              response) { HandlePlayAudio(request, std::move(response)); });
  request_timeout_timer_ = create_wall_timer(
      std::chrono::seconds(1),
      [this]() { CheckRequestTimeout(); });
  session_id_ = "pi-" + std::to_string(now().nanoseconds());
  capture_thread_ = std::thread(&AgentClientNode::CaptureLoop, this);
  RCLCPP_INFO(get_logger(), "C++ Agent Client 已启动：%s，音频服务：%s",
              action_name.c_str(), audio_service_name.c_str());
}

AgentClientNode::~AgentClientNode() {
  stopping_.store(true);
  action_client_->Cancel();
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
  {
    std::lock_guard<std::mutex> lock(request_mutex_);
    active_request_id_ = request_id;
    request_deadline_ = std::chrono::steady_clock::now() + request_timeout_;
  }
  if (!action_client_->Send(request_id, session_id_, std::move(wav),
                            std::move(jpeg))) {
    CompleteRequest(request_id);
  } else {
    RCLCPP_INFO(get_logger(), "已提交多模态请求：%s",
                request_id.substr(0, 16).c_str());
  }
}

void AgentClientNode::HandleResponse(
    const std::string& request_id, AgentActionClient::Response response) {
  if (!IsActiveRequest(request_id)) {
    RCLCPP_WARN(get_logger(), "忽略已超时请求的迟到响应：%s",
                request_id.c_str());
    return;
  }
  for (auto& output : response.outputs) {
    if (output.content_type == small_car_interfaces::msg::AgentContent::TEXT) {
      RCLCPP_INFO(get_logger(), "Agent：%s", output.text.c_str());
    } else if (output.content_type ==
                   small_car_interfaces::msg::AgentContent::JSON &&
               output.name == "robot_task") {
      // 生产运动必须已由 Agent Server 经 Robot Tool Gateway 执行；客户端绝不二次执行。
      RCLCPP_ERROR(get_logger(),
                   "拒绝旧版 robot_task 输出：运动只能由 Robot Tool Gateway 执行");
    }
  }
  if (!response.error_message.empty()) {
    RCLCPP_WARN(get_logger(), "Agent 部分失败：%s",
                response.error_message.c_str());
  }
  CompleteRequest(request_id);
}

void AgentClientNode::HandlePlayAudio(
    const std::shared_ptr<small_car_interfaces::srv::PlayAudio::Request> request,
    std::shared_ptr<small_car_interfaces::srv::PlayAudio::Response> response) {
  auto reject = [&response](std::string code, std::string message) {
    response->accepted = false;
    response->error_code = std::move(code);
    response->message = std::move(message);
  };
  if (request->request_id.empty() || request->utterance_id.empty()) {
    reject("invalid_id", "request_id 和 utterance_id 不能为空");
    return;
  }
  if (request->mime_type != "audio/wav" || request->audio.empty()) {
    reject("invalid_audio", "只接受非空的 audio/wav");
    return;
  }
  if (request->audio.size() > max_playback_bytes_) {
    reject("audio_too_large", "音频超过播放服务大小限制");
    return;
  }

  std::lock_guard<std::mutex> lock(playback_mutex_);
  if (request->utterance_id == last_utterance_id_) {
    response->accepted = true;
    response->message = "重复播报已忽略";
    return;
  }
  if (player_->playing() && !request->interrupt_current) {
    reject("player_busy", "播放器正忙");
    return;
  }
  try {
    player_->Play(std::move(request->audio));
    last_utterance_id_ = request->utterance_id;
    response->accepted = true;
    response->message = "音频已交给后台播放器";
  } catch (const std::exception& error) {
    reject("enqueue_failed", error.what());
  }
}

void AgentClientNode::HandleActionFailure(const std::string& request_id,
                                          const std::string& message) {
  if (!CompleteRequest(request_id)) {
    return;
  }
  RCLCPP_ERROR(get_logger(), "%s", message.c_str());
}

void AgentClientNode::CheckRequestTimeout() {
  std::string timed_out_request;
  {
    std::lock_guard<std::mutex> lock(request_mutex_);
    if (active_request_id_.empty() ||
        std::chrono::steady_clock::now() < request_deadline_) {
      return;
    }
    timed_out_request = std::move(active_request_id_);
    request_active_.store(false);
  }
  action_client_->Cancel(timed_out_request);
  RCLCPP_ERROR(get_logger(),
               "Agent 请求超时，已取消并恢复语音监听：%s（%lld ms）",
               timed_out_request.c_str(),
               static_cast<long long>(request_timeout_.count()));
}

bool AgentClientNode::IsActiveRequest(const std::string& request_id) {
  std::lock_guard<std::mutex> lock(request_mutex_);
  return active_request_id_ == request_id;
}

bool AgentClientNode::CompleteRequest(const std::string& request_id) {
  std::lock_guard<std::mutex> lock(request_mutex_);
  if (active_request_id_ != request_id) {
    return false;
  }
  active_request_id_.clear();
  request_active_.store(false);
  return true;
}

std::string AgentClientNode::NextRequestId() {
  return "pi-" + std::to_string(now().nanoseconds()) + "-" +
         std::to_string(request_sequence_.fetch_add(1));
}

}  // namespace agent_client
