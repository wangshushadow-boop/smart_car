#include "small_car_base/control/command_safety.hpp"

#include <algorithm>

namespace small_car {

CommandSafety::CommandSafety(double max_linear_mps, double max_angular_rad_s,
                             std::chrono::milliseconds timeout,
                             double front_stop_distance_m)
    : max_linear_mps_(max_linear_mps),
      max_angular_rad_s_(max_angular_rad_s),
      timeout_(timeout),
      front_stop_distance_m_(front_stop_distance_m) {}

void CommandSafety::SetCommand(
    const VelocityCommand& command,
    std::chrono::steady_clock::time_point received_at) {
  command_.linear_mps =
      std::clamp(command.linear_mps, -max_linear_mps_, max_linear_mps_);
  command_.angular_rad_s =
      std::clamp(command.angular_rad_s, -max_angular_rad_s_,
                 max_angular_rad_s_);
  received_at_ = received_at;
  have_command_ = true;
  timeout_reported_ = false;
}

void CommandSafety::SetLimits(double max_linear_mps,
                              double max_angular_rad_s) {
  max_linear_mps_ = max_linear_mps;
  max_angular_rad_s_ = max_angular_rad_s;
  command_.linear_mps =
      std::clamp(command_.linear_mps, -max_linear_mps_, max_linear_mps_);
  command_.angular_rad_s =
      std::clamp(command_.angular_rad_s, -max_angular_rad_s_,
                 max_angular_rad_s_);
}

void CommandSafety::SetFrontStopDistance(double front_stop_distance_m) {
  front_stop_distance_m_ = front_stop_distance_m;
}

void CommandSafety::SetFrontRange(double range_m, bool valid) {
  front_range_m_ = range_m;
  front_range_valid_ = valid;
}

SafeCommand CommandSafety::Evaluate(
    std::chrono::steady_clock::time_point now) {
  if (!have_command_) {
    return {};
  }
  if (now - received_at_ > timeout_) {
    have_command_ = false;
    if (!timeout_reported_) {
      timeout_reported_ = true;
      return {CommandState::kTimedOut, {}};
    }
    return {};
  }

  SafeCommand result{CommandState::kActive, command_};
  if (front_range_valid_ && command_.linear_mps > 0.0 &&
      front_range_m_ <= front_stop_distance_m_) {
    result.state = CommandState::kObstacleStop;
    result.velocity.linear_mps = 0.0;
  }
  return result;
}

}  // namespace small_car
