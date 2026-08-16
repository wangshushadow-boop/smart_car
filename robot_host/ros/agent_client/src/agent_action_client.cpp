#include "agent_client/agent_action_client.hpp"

#include <chrono>
#include <utility>

#include <small_car_interfaces/msg/agent_content.hpp>

namespace agent_client {

AgentActionClient::AgentActionClient(rclcpp::Node* node, std::string action_name,
                                     ResultHandler result_handler,
                                     FailureHandler failure_handler)
    : node_(node),
      client_(rclcpp_action::create_client<RunAgent>(node, action_name)),
      result_handler_(std::move(result_handler)),
      failure_handler_(std::move(failure_handler)) {}

bool AgentActionClient::Send(std::string request_id, std::string session_id,
                             std::vector<std::uint8_t> wav,
                             std::vector<std::uint8_t> jpeg) {
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    failure_handler_(request_id, "Agent Action Server 不可用");
    return false;
  }

  const std::string callback_request_id = request_id;

  RunAgent::Goal goal;
  goal.request.request_id = std::move(request_id);
  goal.request.session_id = std::move(session_id);
  goal.request.source = "raspberry_pi";
  goal.request.created_at = node_->now();
  // audio 只声明调用方希望播报；最终 WAV 由 Agent Server 通过
  // /car/audio/enqueue 主动下发，Action 响应仍只承载文字和状态。
  goal.request.response_modalities = {"text", "audio"};
  goal.request.allow_tools = true;
  goal.request.stream_progress = true;

  small_car_interfaces::msg::AgentContent audio;
  audio.content_type = small_car_interfaces::msg::AgentContent::AUDIO;
  audio.name = "user_speech";
  audio.mime_type = "audio/wav";
  audio.data = std::move(wav);
  goal.request.inputs.push_back(std::move(audio));

  if (!jpeg.empty()) {
    small_car_interfaces::msg::AgentContent image;
    image.content_type = small_car_interfaces::msg::AgentContent::IMAGE;
    image.name = "front_camera";
    image.mime_type = "image/jpeg";
    image.data = std::move(jpeg);
    goal.request.inputs.push_back(std::move(image));
  }

  auto options = rclcpp_action::Client<RunAgent>::SendGoalOptions();
  {
    std::lock_guard<std::mutex> lock(goal_mutex_);
    pending_request_id_ = callback_request_id;
    goal_handle_.reset();
  }
  options.goal_response_callback =
      [this, callback_request_id](GoalHandle::SharedPtr handle) {
    bool stale = false;
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      stale = pending_request_id_ != callback_request_id;
      if (!stale) {
        goal_handle_ = handle;
      }
    }
    if (stale) {
      if (handle) {
        client_->async_cancel_goal(handle);
      }
      return;
    }
    if (!handle) {
      failure_handler_(callback_request_id, "Agent 拒绝了请求");
    }
  };
  options.feedback_callback = [this](
                                  GoalHandle::SharedPtr,
                                  const std::shared_ptr<const RunAgent::Feedback>
                                      feedback) {
    RCLCPP_INFO(node_->get_logger(), "Agent %u%%：%s",
                feedback->progress.percent,
                feedback->progress.message.c_str());
  };
  options.result_callback =
      [this, callback_request_id](const GoalHandle::WrappedResult& wrapped) {
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      if (pending_request_id_ == callback_request_id) {
        pending_request_id_.clear();
        goal_handle_.reset();
      }
    }
    if (!wrapped.result) {
      failure_handler_(callback_request_id, "Agent 没有返回结果");
      return;
    }
    result_handler_(callback_request_id, std::move(wrapped.result->response));
  };
  try {
    client_->async_send_goal(goal, options);
  } catch (const std::exception& error) {
    {
      std::lock_guard<std::mutex> lock(goal_mutex_);
      if (pending_request_id_ == callback_request_id) {
        pending_request_id_.clear();
        goal_handle_.reset();
      }
    }
    failure_handler_(callback_request_id,
                     std::string("Agent 请求提交失败：") + error.what());
    return false;
  }
  return true;
}

void AgentActionClient::Cancel(const std::string& request_id) {
  GoalHandle::SharedPtr handle;
  {
    std::lock_guard<std::mutex> lock(goal_mutex_);
    if (pending_request_id_ != request_id) {
      return;
    }
    pending_request_id_.clear();
    handle = std::move(goal_handle_);
  }
  if (handle) {
    client_->async_cancel_goal(handle);
  }
}

void AgentActionClient::Cancel() {
  GoalHandle::SharedPtr handle;
  {
    std::lock_guard<std::mutex> lock(goal_mutex_);
    pending_request_id_.clear();
    handle = std::move(goal_handle_);
  }
  if (handle) {
    client_->async_cancel_goal(handle);
  }
}

}  // namespace agent_client
