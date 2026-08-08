/**
 * @file command_safety.hpp
 * @brief 定义与 ROS 无关的底盘速度命令校验、限幅和失联停车模块。
 */
#ifndef SMALL_CAR_BASE_CONTROL_COMMAND_SAFETY_HPP_
#define SMALL_CAR_BASE_CONTROL_COMMAND_SAFETY_HPP_

#include <chrono>

namespace small_car {

struct VelocityCommand {
  double linear_mps = 0.0;
  double angular_rad_s = 0.0;
};

enum class CommandState {
  kIdle,
  kActive,
  kTimedOut,
  kObstacleStop,
};

struct SafeCommand {
  CommandState state = CommandState::kIdle;
  VelocityCommand velocity;
};

class CommandSafety {
 public:
  CommandSafety(double max_linear_mps, double max_angular_rad_s,
                std::chrono::milliseconds timeout,
                double front_stop_distance_m);

  void SetCommand(const VelocityCommand& command,
                  std::chrono::steady_clock::time_point received_at);
  void SetLimits(double max_linear_mps, double max_angular_rad_s);
  void SetFrontStopDistance(double front_stop_distance_m);
  void SetFrontRange(double range_m, bool valid);
  SafeCommand Evaluate(std::chrono::steady_clock::time_point now);

 private:
  double max_linear_mps_;
  double max_angular_rad_s_;
  std::chrono::milliseconds timeout_;
  double front_stop_distance_m_;
  VelocityCommand command_;
  std::chrono::steady_clock::time_point received_at_{};
  bool have_command_ = false;
  bool timeout_reported_ = false;
  bool front_range_valid_ = false;
  double front_range_m_ = 0.0;
};

}  // namespace small_car

#endif  // SMALL_CAR_BASE_CONTROL_COMMAND_SAFETY_HPP_
