/** @file agent_action_client.hpp @brief 统一 RunAgent Action 的纯通信适配器。 */
#pragma once

#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <small_car_interfaces/action/run_agent.hpp>

namespace agent_client {

class AgentActionClient {
 public:
  using RunAgent = small_car_interfaces::action::RunAgent;
  using Response = small_car_interfaces::msg::AgentResponse;
  using ResultHandler = std::function<void(const std::string&, Response)>;
  using FailureHandler =
      std::function<void(const std::string&, const std::string&)>;

  AgentActionClient(rclcpp::Node* node, std::string action_name,
                    ResultHandler result_handler,
                    FailureHandler failure_handler);

  bool Send(std::string request_id, std::string session_id,
            std::vector<std::uint8_t> wav,
            std::vector<std::uint8_t> jpeg);
  void Cancel(const std::string& request_id);
  void Cancel();

 private:
  using GoalHandle = rclcpp_action::ClientGoalHandle<RunAgent>;

  rclcpp::Node* node_;
  rclcpp_action::Client<RunAgent>::SharedPtr client_;
  ResultHandler result_handler_;
  FailureHandler failure_handler_;
  std::mutex goal_mutex_;
  std::string pending_request_id_;
  GoalHandle::SharedPtr goal_handle_;
};

}  // namespace agent_client
