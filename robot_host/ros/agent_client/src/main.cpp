#include <memory>

#include <rclcpp/rclcpp.hpp>

#include "agent_client/agent_client_node.hpp"

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<agent_client::AgentClientNode>());
  rclcpp::shutdown();
  return 0;
}
