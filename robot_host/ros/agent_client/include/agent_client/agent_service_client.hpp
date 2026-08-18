/** @file agent_service_client.hpp @brief RunAgent Service 的纯通信适配器。 */
#pragma once

#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <small_car_interfaces/srv/run_agent.hpp>

namespace agent_client {

class AgentServiceClient {
 public:
  using RunAgent = small_car_interfaces::srv::RunAgent;
  using Response = small_car_interfaces::msg::AgentResponse;
  using ResultHandler = std::function<void(const std::string&, Response)>;
  using FailureHandler =
      std::function<void(const std::string&, const std::string&)>;

  AgentServiceClient(rclcpp::Node* node, std::string service_name,
                     ResultHandler result_handler,
                     FailureHandler failure_handler);

  bool Send(std::string request_id, std::string session_id,
            std::vector<std::uint8_t> wav,
            std::vector<std::uint8_t> jpeg);
  void Cancel(const std::string& request_id);
  void Cancel();

 private:
  rclcpp::Node* node_;
  rclcpp::Client<RunAgent>::SharedPtr client_;
  ResultHandler result_handler_;
  FailureHandler failure_handler_;
  std::mutex request_mutex_;
  std::string pending_request_id_;
};

}  // namespace agent_client
