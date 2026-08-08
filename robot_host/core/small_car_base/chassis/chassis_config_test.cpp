#include <iostream>
#include <stdexcept>
#include <string>

#include "small_car_base/chassis/chassis_config.hpp"

namespace {

void Expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    throw std::runtime_error("expected chassis YAML path");
  }

  const auto parameters = small_car::LoadChassisConfig(argv[1]);
  Expect(parameters.size() == 24, "chassis parameter count mismatch");
  Expect(small_car::ChassisParameterValue(
             parameters, "max_linear_speed_mm_s") > 0,
         "linear speed limit must be positive");
  Expect(small_car::ChassisParameterValue(
             parameters, "max_angular_speed_mrad_s") > 0,
         "angular speed limit must be positive");
  Expect(small_car::ChassisParameterValue(
             parameters, "ultra_near_distance_mm") >= 0,
         "front stop distance must not be negative");

  std::string validation_error;
  const auto wheel_pwm =
      small_car::MakeChassisParameter("wheel_pwm_min", 550, &validation_error);
  Expect(wheel_pwm.has_value(), "valid runtime parameter must be accepted");
  Expect(wheel_pwm->id == 21, "wheel_pwm_min parameter id mismatch");
  Expect(wheel_pwm->value == 550, "wheel_pwm_min parameter value mismatch");
  Expect(small_car::IsRuntimeTunableChassisParameter("wheel_pwm_min"),
         "wheel_pwm_min must be runtime tunable");
  const auto turn_start_pwm = small_car::MakeChassisParameter(
      "wheel_turn_start_pwm", 750, &validation_error);
  Expect(turn_start_pwm.has_value(), "turn start PWM must be accepted");
  Expect(turn_start_pwm->id == 24, "wheel_turn_start_pwm parameter id mismatch");
  Expect(small_car::IsRuntimeTunableChassisParameter("wheel_turn_start_pwm"),
         "wheel_turn_start_pwm must be runtime tunable");
  Expect(small_car::IsRuntimeTunableChassisParameter(
             "odom_mm_per_tick_num"),
         "odometry calibration must be runtime tunable");
  Expect(small_car::IsRuntimeTunableChassisParameter("wheel_track_mm"),
         "wheel track calibration must be runtime tunable");
  Expect(small_car::IsRuntimeTunableChassisParameter(
             "gyro_lsb_per_dps_x10"),
         "IMU scale calibration must be runtime tunable");
  Expect(!small_car::IsRuntimeTunableChassisParameter("unknown_parameter"),
         "unknown parameter must not be runtime tunable");

  validation_error.clear();
  Expect(!small_car::MakeChassisParameter("wheel_pwm_min", 1001,
                                         &validation_error)
              .has_value(),
         "out-of-range runtime parameter must be rejected");
  Expect(validation_error.find("within [0, 1000]") != std::string::npos,
         "range validation error must include accepted interval");

  validation_error.clear();
  Expect(!small_car::MakeChassisParameter("unknown_parameter", 1,
                                         &validation_error)
              .has_value(),
         "unknown runtime parameter must be rejected");

  bool missing_parameter_rejected = false;
  try {
    (void)small_car::ChassisParameterValue(parameters, "missing");
  } catch (const std::runtime_error&) {
    missing_parameter_rejected = true;
  }
  Expect(missing_parameter_rejected,
         "missing chassis parameter must be rejected");

  std::cout << "chassis config tests passed\n";
  return 0;
}
