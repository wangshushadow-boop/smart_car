#include "agent_client/nav2_motion_client.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace agent_client {
namespace {

constexpr double kPi = 3.14159265358979323846;

builtin_interfaces::msg::Duration ToDuration(double seconds) {
  builtin_interfaces::msg::Duration duration;
  const double safe = std::max(0.0, seconds);
  duration.sec = static_cast<std::int32_t>(safe);
  duration.nanosec = static_cast<std::uint32_t>(
      (safe - static_cast<double>(duration.sec)) * 1000000000.0);
  return duration;
}

}  // namespace

Nav2MotionClient::Nav2MotionClient(rclcpp::Node* node,
                                   std::string drive_action,
                                   std::string spin_action,
                                   double linear_speed_mps,
                                   double timeout_seconds,
                                   EventHandler event_handler)
    : node_(node),
      drive_client_(rclcpp_action::create_client<Drive>(node, drive_action)),
      spin_client_(rclcpp_action::create_client<Spin>(node, spin_action)),
      linear_speed_mps_(linear_speed_mps),
      timeout_seconds_(timeout_seconds),
      event_handler_(std::move(event_handler)) {
  if (linear_speed_mps_ <= 0.0 || timeout_seconds_ <= 0.0) {
    throw std::invalid_argument("Nav2 运动速度和超时必须为正数");
  }
}

bool Nav2MotionClient::Execute(const MotionTask& task) {
  if (task.action == MotionAction::kStop) {
    Stop();
    return true;
  }
  return ExecuteSequence({task});
}

bool Nav2MotionClient::ExecuteSequence(const std::vector<MotionTask>& tasks) {
  if (tasks.empty()) {
    event_handler_("运动序列为空，任务已拒绝");
    return false;
  }
  if (std::any_of(tasks.begin(), tasks.end(), [](const MotionTask& task) {
        return task.action == MotionAction::kStop;
      })) {
    event_handler_("运动序列不能包含停止步骤");
    return false;
  }
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_) {
      event_handler_("已有运动任务正在执行，新任务已拒绝");
      return false;
    }
    // 在发送 Goal 前占用执行槽，避免两个语音请求同时穿透。
    active_ = true;
    cancel_requested_ = false;
    pending_tasks_.assign(tasks.begin(), tasks.end());
    completed_steps_ = 0U;
    total_steps_ = tasks.size();
  }
  event_handler_("开始执行 " + std::to_string(tasks.size()) + " 步运动序列");
  return StartNext();
}

bool Nav2MotionClient::StartNext() {
  MotionTask task;
  std::size_t step_index = 0U;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_ || cancel_requested_ || pending_tasks_.empty()) {
      return false;
    }
    task = pending_tasks_.front();
    pending_tasks_.pop_front();
    step_index = completed_steps_ + 1U;
  }
  event_handler_("正在提交第 " + std::to_string(step_index) + "/" +
                 std::to_string(total_steps_) + " 步");
  const bool sent = task.action == MotionAction::kMoveRelative
                        ? ExecuteDrive(task.value)
                        : ExecuteSpin(task.value);
  if (!sent) {
    FinishCurrent(false, "运动步骤提交失败");
  }
  return sent;
}

bool Nav2MotionClient::ExecuteDrive(double distance_m) {
  if (!drive_client_->wait_for_action_server(std::chrono::seconds(1))) {
    event_handler_("Nav2 DriveOnHeading Action Server 不可用");
    return false;
  }
  Drive::Goal goal;
  goal.target.x = distance_m;
  goal.speed = std::copysign(linear_speed_mps_, distance_m);
  goal.time_allowance = ToDuration(timeout_seconds_);
  goal.disable_collision_checks = false;

  auto options = rclcpp_action::Client<Drive>::SendGoalOptions();
  options.goal_response_callback = [this](DriveHandle::SharedPtr handle) {
    bool cancel = false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      drive_handle_ = std::move(handle);
      cancel = cancel_requested_ && static_cast<bool>(drive_handle_);
      if (!drive_handle_) {
        cancel = false;
      }
    }
    if (!drive_handle_) {
      FinishCurrent(false, "Nav2 拒绝了直线运动任务");
    } else if (cancel) {
      drive_client_->async_cancel_goal(drive_handle_);
    }
  };
  options.result_callback = [this](const DriveHandle::WrappedResult& result) {
    std::string message = "直线运动已完成";
    if (result.code == rclcpp_action::ResultCode::CANCELED) {
      message = "直线运动已取消";
    } else if (result.code != rclcpp_action::ResultCode::SUCCEEDED ||
               (result.result && result.result->error_code != Drive::Result::NONE)) {
      message = "直线运动失败";
      if (result.result && !result.result->error_msg.empty()) {
        message += "：" + result.result->error_msg;
      }
    }
    FinishCurrent(result.code == rclcpp_action::ResultCode::SUCCEEDED &&
                      (!result.result ||
                       result.result->error_code == Drive::Result::NONE),
                  message);
  };
  drive_client_->async_send_goal(goal, options);
  event_handler_("已向 Nav2 提交直线运动任务");
  return true;
}

bool Nav2MotionClient::ExecuteSpin(double angle_deg) {
  if (!spin_client_->wait_for_action_server(std::chrono::seconds(1))) {
    event_handler_("Nav2 Spin Action Server 不可用");
    return false;
  }
  Spin::Goal goal;
  goal.target_yaw = static_cast<float>(angle_deg * kPi / 180.0);
  goal.time_allowance = ToDuration(timeout_seconds_);
  goal.disable_collision_checks = false;
  // 同时记录角度与弧度，确认负号是否在构造 Nav2 Goal 时丢失。
  RCLCPP_INFO(node_->get_logger(),
              "提交 Nav2 Spin：angle_deg=%.6f target_yaw=%.6f rad",
              angle_deg, static_cast<double>(goal.target_yaw));

  auto options = rclcpp_action::Client<Spin>::SendGoalOptions();
  options.goal_response_callback = [this](SpinHandle::SharedPtr handle) {
    bool cancel = false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      spin_handle_ = std::move(handle);
      cancel = cancel_requested_ && static_cast<bool>(spin_handle_);
      if (!spin_handle_) {
        cancel = false;
      }
    }
    if (!spin_handle_) {
      FinishCurrent(false, "Nav2 拒绝了旋转任务");
    } else if (cancel) {
      spin_client_->async_cancel_goal(spin_handle_);
    }
  };
  options.result_callback = [this](const SpinHandle::WrappedResult& result) {
    std::string message = "旋转任务已完成";
    if (result.code == rclcpp_action::ResultCode::CANCELED) {
      message = "旋转任务已取消";
    } else if (result.code != rclcpp_action::ResultCode::SUCCEEDED ||
               (result.result && result.result->error_code != Spin::Result::NONE)) {
      message = "旋转任务失败";
      if (result.result && !result.result->error_msg.empty()) {
        message += "：" + result.result->error_msg;
      }
    }
    FinishCurrent(result.code == rclcpp_action::ResultCode::SUCCEEDED &&
                      (!result.result ||
                       result.result->error_code == Spin::Result::NONE),
                  message);
  };
  spin_client_->async_send_goal(goal, options);
  event_handler_("已向 Nav2 提交旋转任务");
  return true;
}

void Nav2MotionClient::Stop() {
  DriveHandle::SharedPtr drive;
  SpinHandle::SharedPtr spin;
  bool was_active = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    was_active = active_;
    cancel_requested_ = active_;
    pending_tasks_.clear();
    drive = drive_handle_;
    spin = spin_handle_;
  }
  if (drive) {
    drive_client_->async_cancel_goal(drive);
  }
  if (spin) {
    spin_client_->async_cancel_goal(spin);
  }
  event_handler_(was_active ? "正在取消当前 Nav2 运动" : "当前没有运动任务");
}

bool Nav2MotionClient::active() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return active_;
}

void Nav2MotionClient::FinishCurrent(bool success, const std::string& message) {
  bool start_next = false;
  bool sequence_complete = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    drive_handle_.reset();
    spin_handle_.reset();
    if (success && !cancel_requested_) {
      ++completed_steps_;
      start_next = !pending_tasks_.empty();
      sequence_complete = !start_next;
    }
    if (!success || cancel_requested_ || sequence_complete) {
      active_ = false;
      cancel_requested_ = false;
      pending_tasks_.clear();
    }
  }
  event_handler_(message);
  if (start_next) {
    StartNext();
  } else if (sequence_complete && total_steps_ > 1U) {
    event_handler_("组合运动全部完成");
  }
}

}  // namespace agent_client
