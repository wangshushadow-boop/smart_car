/** @file agent_client_node.hpp @brief 树莓派统一多模态 Agent C++ 客户端。 */
#pragma once

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

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
  void HandleResponse(AgentActionClient::Response response);
  void HandleActionFailure(const std::string& message);
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

  std::uint64_t min_speech_ns_ = 0;
  std::uint64_t silence_limit_ns_ = 0;
  std::uint64_t speech_ns_ = 0;
  std::uint64_t silence_ns_ = 0;
  std::string session_id_;
  std::atomic<std::uint64_t> request_sequence_{0};
  std::atomic<bool> request_active_{false};
  std::atomic<bool> stopping_{false};
  std::thread capture_thread_;
};

}  // namespace agent_client
