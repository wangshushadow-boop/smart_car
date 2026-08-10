#include "agent_client/motion_task.hpp"

#include <cassert>
#include <cmath>
#include <string>

int main() {
  agent_client::MotionTaskParser parser({2.0, 180.0});
  std::string error;

  auto forward = parser.Parse(
      R"({"schema":"small_car.motion.v1","action":"move_relative","distance_m":1.0})",
      &error);
  assert(forward.has_value());
  assert(forward->action == agent_client::MotionAction::kMoveRelative);
  assert(std::abs(forward->value - 1.0) < 1.0e-9);

  auto right = parser.Parse(
      R"({"schema":"small_car.motion.v1","action":"rotate_relative","angle_deg":-90})",
      &error);
  assert(right.has_value());
  assert(right->action == agent_client::MotionAction::kRotateRelative);
  assert(std::abs(right->value + 90.0) < 1.0e-9);

  auto stop = parser.Parse(
      R"({"schema":"small_car.motion.v1","action":"stop_motion"})", &error);
  assert(stop.has_value());
  assert(stop->action == agent_client::MotionAction::kStop);

  // 即使服务端被绕过，本地仍拒绝越界、未知字段和伪造 schema。
  assert(!parser.Parse(
      R"({"schema":"small_car.motion.v1","action":"move_relative","distance_m":2.1})",
      &error));
  assert(!parser.Parse(
      R"({"schema":"small_car.motion.v1","action":"move_relative","distance_m":1,"speed_mps":9})",
      &error));
  assert(!parser.Parse(
      R"({"schema":"other","action":"stop_motion"})", &error));
  assert(!parser.Parse("not-json", &error));

  auto sequence = parser.ParseMany(
      R"({"schema":"small_car.motion_sequence.v1","skill":"motion_sequence","steps":[)"
      R"({"schema":"small_car.motion.v1","action":"move_relative","distance_m":1.0},)"
      R"({"schema":"small_car.motion.v1","action":"rotate_relative","angle_deg":-90}]})",
      &error);
  assert(sequence.has_value());
  assert(sequence->size() == 2U);
  assert((*sequence)[0].action == agent_client::MotionAction::kMoveRelative);
  assert((*sequence)[1].action == agent_client::MotionAction::kRotateRelative);
  assert(std::abs((*sequence)[1].value + 90.0) < 1.0e-9);

  // 组合任务仍逐步执行本地安全校验，且不允许嵌入停止操作。
  assert(!parser.ParseMany(
      R"({"schema":"small_car.motion_sequence.v1","skill":"motion_sequence","steps":[)"
      R"({"schema":"small_car.motion.v1","action":"move_relative","distance_m":2.1},)"
      R"({"schema":"small_car.motion.v1","action":"rotate_relative","angle_deg":90}]})",
      &error));
  assert(!parser.ParseMany(
      R"({"schema":"small_car.motion_sequence.v1","skill":"motion_sequence","steps":[)"
      R"({"schema":"small_car.motion.v1","action":"stop_motion"},)"
      R"({"schema":"small_car.motion.v1","action":"rotate_relative","angle_deg":90}]})",
      &error));
  return 0;
}
