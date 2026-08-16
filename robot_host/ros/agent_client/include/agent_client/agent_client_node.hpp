/** @file agent_client_node.hpp @brief 树莓派统一多模态 Agent C++ 客户端。 */
#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <small_car_interfaces/srv/play_audio.hpp>

#include "agent_client/agent_action_client.hpp"
#include "agent_client/camera_sampler.hpp"
#include "agent_client/response_player.hpp"
#include "agent_client/utterance_buffer.hpp"
#include "agent_client/voice_activity_detector.hpp"
#include "small_car_base/audio/audio_device.hpp"
#include "small_car_base/buffer/ring_buffer.hpp"

namespace agent_client {

class AgentClientNode : public rclcpp::Node {
 public:
  AgentClientNode();
  ~AgentClientNode() override;

 private:
  void CaptureLoop();
  void ResetSpeechState();
  void FinishUtterance();
  void HandleResponse(const std::string& request_id,
                      AgentActionClient::Response response);
  void HandleActionFailure(const std::string& request_id,
                           const std::string& message);
  void HandlePlayAudio(
      const std::shared_ptr<small_car_interfaces::srv::PlayAudio::Request> request,
      std::shared_ptr<small_car_interfaces::srv::PlayAudio::Response> response);
  void CheckRequestTimeout();
  bool IsActiveRequest(const std::string& request_id);
  bool CompleteRequest(const std::string& request_id);
  std::string NextRequestId();

  small_car::AudioConfig capture_config_;
  std::unique_ptr<VoiceActivityDetector> vad_;
  std::unique_ptr<UtteranceBuffer> utterance_;
  std::unique_ptr<small_car::RingBuffer<std::uint8_t>> preroll_;
  std::vector<std::uint8_t> idle_period_;
  CameraSampler camera_;
  std::unique_ptr<ResponsePlayer> player_;
  std::unique_ptr<AgentActionClient> action_client_;
  rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr
      image_subscription_;
  rclcpp::Service<small_car_interfaces::srv::PlayAudio>::SharedPtr
      audio_service_;
  rclcpp::TimerBase::SharedPtr request_timeout_timer_;

  std::uint64_t min_speech_ns_ = 0;
  std::uint64_t silence_limit_ns_ = 0;
  std::uint64_t speech_ns_ = 0;
  std::uint64_t silence_ns_ = 0;
  std::string session_id_;
  std::mutex request_mutex_;
  std::mutex playback_mutex_;
  std::string last_utterance_id_;
  std::size_t max_playback_bytes_ = 8U * 1024U * 1024U;
  std::string active_request_id_;
  std::chrono::steady_clock::time_point request_deadline_;
  std::chrono::milliseconds request_timeout_{360000};
  std::atomic<std::uint64_t> request_sequence_{0};
  std::atomic<bool> request_active_{false};
  std::atomic<bool> stopping_{false};
  std::thread capture_thread_;
};

}  // namespace agent_client
