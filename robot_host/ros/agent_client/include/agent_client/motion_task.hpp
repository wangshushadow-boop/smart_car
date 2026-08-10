/** @file motion_task.hpp @brief Agent 声明式运动任务的本地解析与安全校验。 */
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace agent_client {

enum class MotionAction {
  kMoveRelative,
  kRotateRelative,
  kStop,
};

struct MotionTask {
  MotionAction action = MotionAction::kStop;
  double value = 0.0;
};

struct MotionLimits {
  double max_distance_m = 2.0;
  double max_rotation_deg = 180.0;
};

class MotionTaskParser {
 public:
  explicit MotionTaskParser(MotionLimits limits);

  /** 只接受 small_car.motion.v1 JSON，并在树莓派侧重新校验数值范围。 */
  std::optional<MotionTask> Parse(const std::string& json,
                                  std::string* error) const;

  /** 同时接受单步 motion.v1 和最多 8 步的 motion_sequence.v1。 */
  std::optional<std::vector<MotionTask>> ParseMany(
      const std::string& json, std::string* error) const;

 private:
  MotionLimits limits_;
};

}  // namespace agent_client
