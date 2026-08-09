/** @file motion_task.hpp @brief Agent 声明式运动任务的本地解析与安全校验。 */
#pragma once

#include <optional>
#include <string>

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

 private:
  MotionLimits limits_;
};

}  // namespace agent_client
