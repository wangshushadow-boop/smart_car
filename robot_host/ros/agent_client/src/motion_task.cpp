#include "agent_client/motion_task.hpp"

#include <cmath>
#include <set>
#include <stdexcept>
#include <string>

#include <yaml-cpp/yaml.h>

namespace agent_client {
namespace {

constexpr char kMotionSchema[] = "small_car.motion.v1";

bool HasOnlyKeys(const YAML::Node& root,
                 const std::set<std::string>& allowed) {
  for (const auto& entry : root) {
    if (!entry.first.IsScalar() ||
        allowed.count(entry.first.as<std::string>()) == 0U) {
      return false;
    }
  }
  return true;
}

double RequiredFiniteNumber(const YAML::Node& root, const char* key) {
  const auto value = root[key];
  if (!value || !value.IsScalar()) {
    throw std::invalid_argument(std::string("缺少数值字段：") + key);
  }
  const double result = value.as<double>();
  if (!std::isfinite(result)) {
    throw std::invalid_argument(std::string("字段不是有限数值：") + key);
  }
  return result;
}

}  // namespace

MotionTaskParser::MotionTaskParser(MotionLimits limits) : limits_(limits) {
  if (limits_.max_distance_m <= 0.0 || limits_.max_rotation_deg <= 0.0) {
    throw std::invalid_argument("运动任务限制必须为正数");
  }
}

std::optional<MotionTask> MotionTaskParser::Parse(const std::string& json,
                                                   std::string* error) const {
  auto fail = [error](const std::string& message) {
    if (error != nullptr) {
      *error = message;
    }
    return std::optional<MotionTask>();
  };
  if (json.size() < 2U || json.front() != '{' || json.back() != '}') {
    return fail("运动任务必须是 JSON 对象");
  }
  try {
    const auto root = YAML::Load(json);
    if (!root.IsMap() || !root["schema"] || !root["action"] ||
        root["schema"].as<std::string>() != kMotionSchema) {
      return fail("运动任务 schema 无效");
    }
    const std::string action = root["action"].as<std::string>();
    if (action == "move_relative") {
      if (!HasOnlyKeys(root, {"schema", "action", "distance_m"})) {
        return fail("直线任务包含未允许字段");
      }
      const double distance = RequiredFiniteNumber(root, "distance_m");
      if (std::abs(distance) < 0.05 ||
          std::abs(distance) > limits_.max_distance_m) {
        return fail("移动距离超出本地安全范围");
      }
      return MotionTask{MotionAction::kMoveRelative, distance};
    }
    if (action == "rotate_relative") {
      if (!HasOnlyKeys(root, {"schema", "action", "angle_deg"})) {
        return fail("旋转任务包含未允许字段");
      }
      const double angle = RequiredFiniteNumber(root, "angle_deg");
      if (std::abs(angle) < 1.0 ||
          std::abs(angle) > limits_.max_rotation_deg) {
        return fail("旋转角度超出本地安全范围");
      }
      return MotionTask{MotionAction::kRotateRelative, angle};
    }
    if (action == "stop_motion") {
      if (!HasOnlyKeys(root, {"schema", "action"})) {
        return fail("停止任务包含未允许字段");
      }
      return MotionTask{MotionAction::kStop, 0.0};
    }
    return fail("不支持的运动任务类型");
  } catch (const std::exception& exception) {
    return fail(std::string("运动任务解析失败：") + exception.what());
  }
}

}  // namespace agent_client
