#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

#include <nav2_msgs/action/drive_on_heading.hpp>
#include <nav2_msgs/action/spin.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <small_car_interfaces/action/execute_robot_tool.hpp>
#include <small_car_interfaces/msg/agent_content.hpp>
#include <trajectory_msgs/msg/joint_trajectory.hpp>
#include <trajectory_msgs/msg/joint_trajectory_point.hpp>
#include <yaml-cpp/yaml.h>

namespace {

using namespace std::chrono_literals;
constexpr double kPi = 3.14159265358979323846;

builtin_interfaces::msg::Duration ToDuration(double seconds) {
  builtin_interfaces::msg::Duration result;
  result.sec = static_cast<std::int32_t>(seconds);
  result.nanosec = static_cast<std::uint32_t>(
      (seconds - static_cast<double>(result.sec)) * 1000000000.0);
  return result;
}

double RequiredNumber(const YAML::Node& arguments, const char* name) {
  if (!arguments.IsMap() || !arguments[name] || arguments.size() != 1U) {
    throw std::invalid_argument(std::string("工具参数必须且只能包含 ") + name);
  }
  const double value = arguments[name].as<double>();
  if (!std::isfinite(value)) {
    throw std::invalid_argument(std::string(name) + " 必须为有限数值");
  }
  return value;
}

void RequireEmptyArguments(const YAML::Node& arguments) {
  if (!arguments.IsMap() || arguments.size() != 0U) {
    throw std::invalid_argument("该工具不接受参数");
  }
}

}  // namespace

class RobotToolGateway final : public rclcpp::Node {
 public:
  using Tool = small_car_interfaces::action::ExecuteRobotTool;
  using ToolHandle = rclcpp_action::ServerGoalHandle<Tool>;
  using Drive = nav2_msgs::action::DriveOnHeading;
  using Spin = nav2_msgs::action::Spin;

  RobotToolGateway() : Node("robot_tool_gateway") {
    const auto tool_action = declare_parameter<std::string>("tool_action", "");
    const auto drive_action = declare_parameter<std::string>("drive_action", "");
    const auto spin_action = declare_parameter<std::string>("spin_action", "");
    const auto servo_topic = declare_parameter<std::string>("servo_topic", "");
    const auto image_topic = declare_parameter<std::string>("image_topic", "");
    linear_speed_mps_ = declare_parameter<double>("linear_speed_mps", 0.2);
    motion_timeout_seconds_ = declare_parameter<double>("motion_timeout_seconds", 15.0);
    if (tool_action.empty() || drive_action.empty() || spin_action.empty() ||
        servo_topic.empty() || image_topic.empty()) {
      throw std::invalid_argument("Robot Tool Gateway 接口参数不能为空");
    }

    drive_client_ = rclcpp_action::create_client<Drive>(this, drive_action);
    spin_client_ = rclcpp_action::create_client<Spin>(this, spin_action);
    servo_pub_ = create_publisher<trajectory_msgs::msg::JointTrajectory>(servo_topic, 10);
    image_sub_ = create_subscription<sensor_msgs::msg::CompressedImage>(
        image_topic, rclcpp::SensorDataQoS(),
        [this](sensor_msgs::msg::CompressedImage::ConstSharedPtr image) {
          std::lock_guard<std::mutex> lock(image_mutex_);
          latest_image_ = std::move(image);
        });
    tool_server_ = rclcpp_action::create_server<Tool>(
        this, tool_action,
        [this](const rclcpp_action::GoalUUID&, std::shared_ptr<const Tool::Goal> goal) {
          return AcceptGoal(*goal);
        },
        [](const std::shared_ptr<ToolHandle>) {
          return rclcpp_action::CancelResponse::ACCEPT;
        },
        [this](std::shared_ptr<ToolHandle> handle) {
          std::thread([this, handle = std::move(handle)] { Execute(handle); }).detach();
        });
    RCLCPP_INFO(get_logger(), "Robot Tool Gateway 已启动：%s", tool_action.c_str());
  }

 private:
  rclcpp_action::GoalResponse AcceptGoal(const Tool::Goal& goal) {
    if (goal.task_id.empty() || goal.step_id == 0U || goal.tool_name.empty()) {
      return rclcpp_action::GoalResponse::REJECT;
    }
    std::lock_guard<std::mutex> lock(state_mutex_);
    const std::string key = goal.task_id + ":" + std::to_string(goal.step_id);
    if (completed_steps_.count(key) != 0U || active_) {
      return rclcpp_action::GoalResponse::REJECT;
    }
    active_ = true;
    active_key_ = key;
    return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
  }

  void Execute(const std::shared_ptr<ToolHandle>& handle) {
    auto result = std::make_shared<Tool::Result>();
    const auto& goal = *handle->get_goal();
    try {
      YAML::Node arguments = YAML::Load(goal.arguments_json.empty() ? "{}" : goal.arguments_json);
      result->success = ExecuteTool(goal.tool_name, arguments, handle, result->message);
      result->error_code = result->success ? "" : "execution_failed";
      result->result_json = result->success ? "{\"executed\":true}" : "{}";
      if (goal.request_observation || goal.tool_name == "capture_camera") {
        AddLatestImage(result.get());
      }
    } catch (const std::exception& error) {
      result->success = false;
      result->error_code = "invalid_arguments";
      result->message = error.what();
      result->result_json = "{}";
    }

    const bool canceled = handle->is_canceling();
    {
      std::lock_guard<std::mutex> lock(state_mutex_);
      completed_steps_.insert(active_key_);
      if (completed_steps_.size() > 4096U) {
        completed_steps_.clear();
      }
      active_ = false;
      active_key_.clear();
    }
    if (canceled) {
      handle->canceled(result);
    } else if (result->success) {
      handle->succeed(result);
    } else {
      handle->abort(result);
    }
  }

  bool ExecuteTool(const std::string& name, const YAML::Node& arguments,
                   const std::shared_ptr<ToolHandle>& handle, std::string& message) {
    PublishFeedback(handle, "validating", 10U, "树莓派正在校验工具参数");
    if (name == "move_relative") {
      const double distance = RequiredNumber(arguments, "distance_m");
      if (std::abs(distance) < 0.05 || std::abs(distance) > 2.0) {
        throw std::invalid_argument("distance_m 必须在 ±0.05～±2.0 米范围内");
      }
      return ExecuteDrive(distance, handle, message);
    }
    if (name == "rotate_relative") {
      const double angle = RequiredNumber(arguments, "angle_deg");
      if (std::abs(angle) < 1.0 || std::abs(angle) > 180.0) {
        throw std::invalid_argument("angle_deg 必须在 ±1～±180 度范围内");
      }
      return ExecuteSpin(angle, handle, message);
    }
    if (name == "stop_motion") {
      RequireEmptyArguments(arguments);
      drive_client_->async_cancel_all_goals();
      spin_client_->async_cancel_all_goals();
      message = "已请求停止当前运动";
      return true;
    }
    if (name == "set_camera_pan") {
      return SetServo("upper_servo_joint", RequiredNumber(arguments, "angle_deg"),
                      -90.0, 90.0, handle, message);
    }
    if (name == "set_camera_tilt") {
      return SetServo("lower_servo_joint", RequiredNumber(arguments, "angle_deg"),
                      -45.0, 45.0, handle, message);
    }
    if (name == "capture_camera") {
      RequireEmptyArguments(arguments);
      message = "已获取最新相机画面";
      return true;
    }
    throw std::invalid_argument("未知或未授权工具：" + name);
  }

  bool ExecuteDrive(double distance, const std::shared_ptr<ToolHandle>& outer,
                    std::string& message) {
    if (!drive_client_->wait_for_action_server(1s)) {
      message = "Nav2 DriveOnHeading 不可用";
      return false;
    }
    Drive::Goal goal;
    goal.target.x = distance;
    goal.speed = std::copysign(linear_speed_mps_, distance);
    goal.time_allowance = ToDuration(motion_timeout_seconds_);
    goal.disable_collision_checks = false;
    PublishFeedback(outer, "executing", 30U, "正在执行直线运动");
    auto handle_future = drive_client_->async_send_goal(goal);
    if (handle_future.wait_for(2s) != std::future_status::ready || !handle_future.get()) {
      message = "Nav2 拒绝直线运动";
      return false;
    }
    auto inner = handle_future.get();
    auto result_future = drive_client_->async_get_result(inner);
    return WaitMotion(result_future, outer,
                      [this, inner] { drive_client_->async_cancel_goal(inner); },
                      "直线运动", message);
  }

  bool ExecuteSpin(double angle_deg, const std::shared_ptr<ToolHandle>& outer,
                   std::string& message) {
    if (!spin_client_->wait_for_action_server(1s)) {
      message = "Nav2 Spin 不可用";
      return false;
    }
    Spin::Goal goal;
    goal.target_yaw = static_cast<float>(angle_deg * kPi / 180.0);
    goal.time_allowance = ToDuration(motion_timeout_seconds_);
    goal.disable_collision_checks = false;
    PublishFeedback(outer, "executing", 30U, "正在执行旋转运动");
    auto handle_future = spin_client_->async_send_goal(goal);
    if (handle_future.wait_for(2s) != std::future_status::ready || !handle_future.get()) {
      message = "Nav2 拒绝旋转运动";
      return false;
    }
    auto inner = handle_future.get();
    auto result_future = spin_client_->async_get_result(inner);
    return WaitMotion(result_future, outer,
                      [this, inner] { spin_client_->async_cancel_goal(inner); },
                      "旋转运动", message);
  }

  template <typename Future, typename Cancel>
  bool WaitMotion(Future& future, const std::shared_ptr<ToolHandle>& outer,
                  Cancel cancel, const std::string& label, std::string& message) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::duration<double>(motion_timeout_seconds_ + 2.0);
    while (future.wait_for(50ms) != std::future_status::ready) {
      if (outer->is_canceling() || std::chrono::steady_clock::now() >= deadline) {
        cancel();
        message = outer->is_canceling() ? label + "已取消" : label + "执行超时";
        return false;
      }
    }
    const auto wrapped = future.get();
    const bool success = wrapped.code == rclcpp_action::ResultCode::SUCCEEDED;
    message = success ? label + "已完成" : label + "执行失败";
    PublishFeedback(outer, "completed", 100U, message);
    return success;
  }

  bool SetServo(const std::string& joint, double angle_deg, double min_deg,
                double max_deg, const std::shared_ptr<ToolHandle>& handle,
                std::string& message) {
    if (angle_deg < min_deg || angle_deg > max_deg) {
      throw std::invalid_argument("云台角度超出机械安全范围");
    }
    trajectory_msgs::msg::JointTrajectory trajectory;
    trajectory.header.stamp = now();
    trajectory.joint_names = {joint};
    trajectory_msgs::msg::JointTrajectoryPoint point;
    point.positions = {angle_deg * kPi / 180.0};
    point.time_from_start = ToDuration(0.5);
    trajectory.points.push_back(std::move(point));
    servo_pub_->publish(trajectory);
    PublishFeedback(handle, "executing", 50U, "云台目标已下发");
    std::this_thread::sleep_for(500ms);
    message = "云台角度已设置";
    return !handle->is_canceling();
  }

  static void PublishFeedback(const std::shared_ptr<ToolHandle>& handle,
                              const std::string& stage, std::uint8_t percent,
                              const std::string& message) {
    auto feedback = std::make_shared<Tool::Feedback>();
    feedback->stage = stage;
    feedback->percent = percent;
    feedback->message = message;
    handle->publish_feedback(feedback);
  }

  void AddLatestImage(Tool::Result* result) {
    sensor_msgs::msg::CompressedImage::ConstSharedPtr image;
    {
      std::lock_guard<std::mutex> lock(image_mutex_);
      image = latest_image_;
    }
    if (!image) {
      return;
    }
    small_car_interfaces::msg::AgentContent observation;
    observation.content_type = small_car_interfaces::msg::AgentContent::IMAGE;
    observation.name = "front_camera";
    observation.mime_type = image->format.find("png") != std::string::npos
                                ? "image/png"
                                : "image/jpeg";
    observation.data = image->data;
    result->observations.push_back(std::move(observation));
  }

  double linear_speed_mps_{0.2};
  double motion_timeout_seconds_{15.0};
  std::mutex state_mutex_;
  bool active_{false};
  std::string active_key_;
  std::unordered_set<std::string> completed_steps_;
  std::mutex image_mutex_;
  sensor_msgs::msg::CompressedImage::ConstSharedPtr latest_image_;
  rclcpp_action::Client<Drive>::SharedPtr drive_client_;
  rclcpp_action::Client<Spin>::SharedPtr spin_client_;
  rclcpp_action::Server<Tool>::SharedPtr tool_server_;
  rclcpp::Publisher<trajectory_msgs::msg::JointTrajectory>::SharedPtr servo_pub_;
  rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr image_sub_;
};

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::executors::MultiThreadedExecutor executor(rclcpp::ExecutorOptions(), 4U);
  // Executor 内部不负责延长临时节点对象的生命周期，必须由 main 持有强引用。
  // 否则构造日志打印后节点立即析构，进程仍空转但 Action Server 会从 ROS 图消失。
  auto node = std::make_shared<RobotToolGateway>();
  executor.add_node(node);
  executor.spin();
  executor.remove_node(node);
  node.reset();
  rclcpp::shutdown();
  return 0;
}
