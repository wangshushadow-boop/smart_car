/**
 * @file gimbal_controller.hpp
 * @brief 定义上下两路云台舵机角度到 MCU PWM 的映射。
 */
#ifndef SMALL_CAR_BASE_SERVO_GIMBAL_CONTROLLER_HPP_
#define SMALL_CAR_BASE_SERVO_GIMBAL_CONTROLLER_HPP_

#include <cstdint>

namespace small_car {

struct ServoMapping {
  int center_us = 1500;
  int min_us = 800;
  int max_us = 2200;
  double range_rad = 3.14159265358979323846;
  double sign = 1.0;
};

struct GimbalCommand {
  double upper_rad = 0.0;
  double lower_rad = 0.0;
};

struct GimbalPulse {
  std::uint16_t upper_us = 1500;
  std::uint16_t lower_us = 1500;
};

class GimbalController {
 public:
  GimbalController(const ServoMapping& upper, const ServoMapping& lower);

  void SetUpper(double radians);
  void SetLower(double radians);
  const GimbalCommand& command() const;
  GimbalPulse pulse() const;

 private:
  static std::uint16_t ToPulse(double radians,
                               const ServoMapping& mapping);

  ServoMapping upper_;
  ServoMapping lower_;
  GimbalCommand command_;
};

}  // namespace small_car

#endif  // SMALL_CAR_BASE_SERVO_GIMBAL_CONTROLLER_HPP_
