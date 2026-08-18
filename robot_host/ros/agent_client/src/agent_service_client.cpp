#include "agent_client/agent_service_client.hpp"

#include <chrono>
#include <utility>

#include <small_car_interfaces/msg/agent_content.hpp>

namespace agent_client {

AgentServiceClient::AgentServiceClient(rclcpp::Node* node,
                                       std::string service_name,
                                       ResultHandler result_handler,
                                       FailureHandler failure_handler)
    : node_(node),
      client_(node->create_client<RunAgent>(service_name)),
      result_handler_(std::move(result_handler)),
      failure_handler_(std::move(failure_handler)) {}

bool AgentServiceClient::Send(std::string request_id, std::string session_id,
                              std::vector<std::uint8_t> wav,
                              std::vector<std::uint8_t> jpeg) {
  if (!client_->wait_for_service(std::chrono::seconds(1))) {
    failure_handler_(request_id, "Agent Service 不可用");
    return false;
  }

  const std::string callback_request_id = request_id;
  auto service_request = std::make_shared<RunAgent::Request>();
  service_request->request.request_id = std::move(request_id);
  service_request->request.session_id = std::move(session_id);
  service_request->request.source = "raspberry_pi";
  service_request->request.created_at = node_->now();
  // Service 只等待 DialogueLoop 快速响应；最终语音由播放 Service 主动下发。
  service_request->request.response_modalities = {"text", "audio"};
  service_request->request.allow_tools = true;

  small_car_interfaces::msg::AgentContent audio;
  audio.content_type = small_car_interfaces::msg::AgentContent::AUDIO;
  audio.name = "user_speech";
  audio.mime_type = "audio/wav";
  audio.data = std::move(wav);
  service_request->request.inputs.push_back(std::move(audio));

  if (!jpeg.empty()) {
    small_car_interfaces::msg::AgentContent image;
    image.content_type = small_car_interfaces::msg::AgentContent::IMAGE;
    image.name = "front_camera";
    image.mime_type = "image/jpeg";
    image.data = std::move(jpeg);
    service_request->request.inputs.push_back(std::move(image));
  }

  {
    std::lock_guard<std::mutex> lock(request_mutex_);
    pending_request_id_ = callback_request_id;
  }
  try {
    client_->async_send_request(
        service_request,
        [this, callback_request_id](rclcpp::Client<RunAgent>::SharedFuture future) {
          {
            std::lock_guard<std::mutex> lock(request_mutex_);
            if (pending_request_id_ != callback_request_id) {
              return;
            }
            pending_request_id_.clear();
          }
          try {
            auto response = future.get();
            if (!response) {
              failure_handler_(callback_request_id, "Agent 没有返回结果");
              return;
            }
            result_handler_(callback_request_id, std::move(response->response));
          } catch (const std::exception& error) {
            failure_handler_(callback_request_id,
                             std::string("Agent Service 调用失败：") + error.what());
          }
        });
  } catch (const std::exception& error) {
    Cancel(callback_request_id);
    failure_handler_(callback_request_id,
                     std::string("Agent 请求提交失败：") + error.what());
    return false;
  }
  return true;
}

void AgentServiceClient::Cancel(const std::string& request_id) {
  std::lock_guard<std::mutex> lock(request_mutex_);
  if (pending_request_id_ == request_id) {
    // ROS Service 不支持取消；清除关联后会安全忽略迟到响应。
    pending_request_id_.clear();
  }
}

void AgentServiceClient::Cancel() {
  std::lock_guard<std::mutex> lock(request_mutex_);
  pending_request_id_.clear();
}

}  // namespace agent_client
