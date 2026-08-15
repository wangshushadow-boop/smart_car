#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>

namespace small_car {

struct TrajectoryPose {
  double x{0.0};
  double y{0.0};
  double z{0.0};
  double orientation_x{0.0};
  double orientation_y{0.0};
  double orientation_z{0.0};
  double orientation_w{1.0};
  std::int64_t timestamp_ns{0};
};

class PathAccumulator {
 public:
  PathAccumulator(std::size_t max_points, double min_distance_m);

  bool Add(const TrajectoryPose& pose);
  void Clear();

  const std::deque<TrajectoryPose>& poses() const { return poses_; }

 private:
  std::size_t max_points_;
  double min_distance_m_;
  std::deque<TrajectoryPose> poses_;
};

}  // namespace small_car
