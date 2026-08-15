#include "small_car_base/trajectory/path_accumulator.hpp"

#include <cmath>
#include <stdexcept>

namespace {

void Expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

}  // namespace

int main() {
  small_car::PathAccumulator path(2, 0.1);
  small_car::TrajectoryPose pose;
  Expect(path.Add(pose), "first pose must be accepted");

  pose.x = 0.05;
  Expect(!path.Add(pose), "pose below sampling distance must be rejected");
  Expect(path.poses().size() == 1, "rejected pose must not change path");

  pose.x = 0.1;
  Expect(path.Add(pose), "pose at sampling distance must be accepted");
  pose.x = 0.3;
  Expect(path.Add(pose), "distant pose must be accepted");
  Expect(path.poses().size() == 2, "path must remain bounded");
  Expect(std::abs(path.poses().front().x - 0.1) < 1.0e-9,
         "oldest pose must be evicted");

  path.Clear();
  Expect(path.poses().empty(), "clear must remove every pose");

  bool rejected_invalid_config = false;
  try {
    small_car::PathAccumulator invalid(0, 0.1);
  } catch (const std::invalid_argument&) {
    rejected_invalid_config = true;
  }
  Expect(rejected_invalid_config, "zero capacity must be rejected");
  return 0;
}
