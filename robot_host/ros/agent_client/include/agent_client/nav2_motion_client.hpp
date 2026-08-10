/** @file nav2_motion_client.hpp @brief 受控的 Nav2 相对运动 Action Client。 */
#pragma once

#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <nav2_msgs/action/drive_on_heading.hpp>
#include <nav2_msgs/action/spin.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include "agent_client/motion_task.hpp"

namespace agent_client {

class Nav2MotionClient {
 public:
  using EventHandler = std::function<void(const std::string&)>;

  Nav2MotionClient(rclcpp::Node* node, std::string drive_action,
                   std::string spin_action, double linear_speed_mps,
                   double timeout_seconds, EventHandler event_handler);

  /** 提交单个受控运动；运动未结束时拒绝新的非停止任务。 */
  bool Execute(const MotionTask& task);
  /** 串行执行受控运动序列；任一步失败或取消都会清空剩余步骤。 */
  bool ExecuteSequence(const std::vector<MotionTask>& tasks);
  void Stop();
  bool active() const;

 private:
  using Drive = nav2_msgs::action::DriveOnHeading;
  using Spin = nav2_msgs::action::Spin;
  using DriveHandle = rclcpp_action::ClientGoalHandle<Drive>;
  using SpinHandle = rclcpp_action::ClientGoalHandle<Spin>;

  bool ExecuteDrive(double distance_m);
  bool ExecuteSpin(double angle_deg);
  bool StartNext();
  void FinishCurrent(bool success, const std::string& message);

  rclcpp::Node* node_;
  rclcpp_action::Client<Drive>::SharedPtr drive_client_;
  rclcpp_action::Client<Spin>::SharedPtr spin_client_;
  double linear_speed_mps_;
  double timeout_seconds_;
  EventHandler event_handler_;

  mutable std::mutex mutex_;
  bool active_ = false;
  bool cancel_requested_ = false;
  std::deque<MotionTask> pending_tasks_;
  std::size_t completed_steps_ = 0U;
  std::size_t total_steps_ = 0U;
  DriveHandle::SharedPtr drive_handle_;
  SpinHandle::SharedPtr spin_handle_;
};

}  // namespace agent_client
