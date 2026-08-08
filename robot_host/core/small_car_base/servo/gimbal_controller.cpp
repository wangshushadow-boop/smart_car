#include "small_car_base/servo/gimbal_controller.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace small_car {

GimbalController::GimbalController(const ServoMapping& upper,
                                   const ServoMapping& lower)
    : upper_(upper), lower_(lower) {
  const auto valid = [](const ServoMapping& mapping) {
    return mapping.min_us <= mapping.center_us &&
           mapping.center_us <= mapping.max_us && mapping.range_rad > 0.0;
  };
  if (!valid(upper_) || !valid(lower_)) {
    throw std::invalid_argument("invalid gimbal servo mapping");
  }
}

void GimbalController::SetUpper(double radians) {
  command_.upper_rad = radians;
}

void GimbalController::SetLower(double radians) {
  command_.lower_rad = radians;
}

const GimbalCommand& GimbalController::command() const {
  return command_;
}

GimbalPulse GimbalController::pulse() const {
  return {ToPulse(command_.upper_rad, upper_),
          ToPulse(command_.lower_rad, lower_)};
}

std::uint16_t GimbalController::ToPulse(
    double radians, const ServoMapping& mapping) {
  double normalized = 2.0 * radians / mapping.range_rad;
  normalized = std::clamp(normalized * mapping.sign, -1.0, 1.0);
  const double pulse =
      normalized >= 0.0
          ? mapping.center_us +
                normalized * (mapping.max_us - mapping.center_us)
          : mapping.center_us +
                normalized * (mapping.center_us - mapping.min_us);
  return static_cast<std::uint16_t>(std::lround(pulse));
}

}  // namespace small_car
