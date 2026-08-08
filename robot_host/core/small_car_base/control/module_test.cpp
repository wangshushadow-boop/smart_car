#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>

#include "small_car_base/control/command_safety.hpp"
#include "small_car_base/servo/gimbal_controller.hpp"

namespace {

void Expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() {
  using namespace std::chrono_literals;

  const auto start = std::chrono::steady_clock::time_point{};
  small_car::CommandSafety safety(0.6, 2.0, 500ms, 0.2);
  safety.SetCommand({1.0, -3.0}, start);
  auto command = safety.Evaluate(start + 10ms);
  Expect(command.state == small_car::CommandState::kActive,
         "fresh command must be active");
  Expect(std::abs(command.velocity.linear_mps - 0.6) < 1e-9,
         "linear velocity must be limited");
  Expect(std::abs(command.velocity.angular_rad_s + 2.0) < 1e-9,
         "angular velocity must be limited");

  safety.SetFrontRange(0.1, true);
  command = safety.Evaluate(start + 20ms);
  Expect(command.state == small_car::CommandState::kObstacleStop,
         "near obstacle must stop forward motion");
  Expect(command.velocity.linear_mps == 0.0,
         "obstacle stop must zero linear velocity");

  safety.SetLimits(0.3, 1.0);
  safety.SetFrontStopDistance(0.05);
  safety.SetCommand({0.8, -2.0}, start + 30ms);
  command = safety.Evaluate(start + 40ms);
  Expect(command.state == small_car::CommandState::kActive,
         "updated stop distance must take effect");
  Expect(std::abs(command.velocity.linear_mps - 0.3) < 1e-9,
         "updated linear limit must take effect");
  Expect(std::abs(command.velocity.angular_rad_s + 1.0) < 1e-9,
         "updated angular limit must take effect");

  command = safety.Evaluate(start + 600ms);
  Expect(command.state == small_car::CommandState::kTimedOut,
         "expired command must request one stop");
  Expect(safety.Evaluate(start + 610ms).state ==
             small_car::CommandState::kIdle,
         "expired command must become idle after stop");

  small_car::ServoMapping upper;
  small_car::ServoMapping lower;
  lower.center_us = 1250;
  lower.min_us = 800;
  lower.max_us = 1700;
  small_car::GimbalController gimbal(upper, lower);
  gimbal.SetUpper(0.0);
  gimbal.SetLower(0.0);
  const auto pulse = gimbal.pulse();
  Expect(pulse.upper_us == 1500, "upper center pulse mismatch");
  Expect(pulse.lower_us == 1250, "lower center pulse mismatch");

  std::cout << "module tests passed\n";
  return 0;
}
