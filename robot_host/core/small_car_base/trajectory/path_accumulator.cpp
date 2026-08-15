#include "small_car_base/trajectory/path_accumulator.hpp"

#include <cmath>
#include <stdexcept>

namespace small_car {

PathAccumulator::PathAccumulator(std::size_t max_points, double min_distance_m)
    : max_points_(max_points), min_distance_m_(min_distance_m) {
  if (max_points_ == 0) {
    throw std::invalid_argument("max_points must be positive");
  }
  if (!std::isfinite(min_distance_m_) || min_distance_m_ < 0.0) {
    throw std::invalid_argument("min_distance_m must be finite and non-negative");
  }
}

bool PathAccumulator::Add(const TrajectoryPose& pose) {
  if (!poses_.empty()) {
    const auto& previous = poses_.back();
    const double dx = pose.x - previous.x;
    const double dy = pose.y - previous.y;
    const double dz = pose.z - previous.z;
    if (std::sqrt(dx * dx + dy * dy + dz * dz) < min_distance_m_) {
      return false;
    }
  }

  poses_.push_back(pose);
  while (poses_.size() > max_points_) {
    poses_.pop_front();
  }
  return true;
}

void PathAccumulator::Clear() { poses_.clear(); }

}  // namespace small_car
