/**
 * @file base_node.cpp
 * @brief 实现小车唯一的 ROS 2 底盘节点。
 *
 * 节点只承担 ROS 接口和模块调度。协议、命令安全和云台映射分别由纯 C++
 * 模块实现；Nav2 负责规划、行为、碰撞监控和正常速度平滑。
 */
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <functional>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <ament_index_cpp/get_package_share_directory.hpp>
#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <diagnostic_msgs/msg/diagnostic_status.hpp>
#include <diagnostic_msgs/msg/key_value.hpp>
#include <geometry_msgs/msg/twist_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <rcl_interfaces/msg/set_parameters_result.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <sensor_msgs/msg/range.hpp>
#include <trajectory_msgs/msg/joint_trajectory.hpp>

#include "small_car_base/buffer/ring_buffer.hpp"
#include "small_car_base/chassis/chassis_config.hpp"
#include "small_car_base/control/command_safety.hpp"
#include "small_car_base/mcu/car_client.hpp"
#include "small_car_base/servo/gimbal_controller.hpp"

namespace small_car_base {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kDegreesToRadians = kPi / 180.0;
constexpr double kGravity = 9.80665;

constexpr double kEncoderMillimeterDenominator = 15600.0;
constexpr std::uint32_t kMaximumEncoderIntervalMs = 500;
constexpr std::int64_t kMaximumEncoderDelta = 10000;

/** 使用无符号减法计算累计编码器差值，可自然处理 int32 计数回绕。 */
std::int32_t CounterDelta(std::int32_t current, std::int32_t previous) {
  return static_cast<std::int32_t>(
      static_cast<std::uint32_t>(current) -
      static_cast<std::uint32_t>(previous));
}

/** 构造一项 diagnostic_msgs 键值，减少诊断发布代码的重复。 */
diagnostic_msgs::msg::KeyValue DiagnosticValue(const std::string& key,
                                                const std::string& value) {
  diagnostic_msgs::msg::KeyValue result;
  result.key = key;
  result.value = value;
  return result;
}

}  // namespace

/**
 * ROS 2 与 MCU 的唯一串口桥接节点。
 *
 * 节点拥有串口设备，并把 MCU 的整数协议单位转换为 ROS SI 单位。其它节点不应
 * 直接打开同一串口，以免两进程分走字节导致协议帧损坏。
 */
class SmallCarBaseNode : public rclcpp::Node {
 public:
  /** 按依赖顺序初始化：参数 -> 串口 -> ROS 接口 -> MCU 参数 -> 遥测开关。 */
  SmallCarBaseNode() : Node("small_car_base") {
    // 构造阶段只做一次性初始化：读取 ROS 参数、打开串口、下发底盘参数、创建话题和定时器。
    DeclareParameters();
    ReadParameters();
    ultrasonic_samples_ =
        std::make_unique<small_car::RingBuffer<double>>(ultrasonic_filter_window_);
    command_safety_ = std::make_unique<small_car::CommandSafety>(
        max_linear_speed_mps_, max_angular_speed_rad_s_, cmd_vel_timeout_,
        front_stop_distance_m_);
    gimbal_ = std::make_unique<small_car::GimbalController>(
        upper_servo_mapping_, lower_servo_mapping_);
    OpenController();
    CreateRosInterfaces();
    ApplyControllerConfig();
    ConfigureTelemetry();
    RCLCPP_INFO(get_logger(), "small car base ready: %s @ %d", serial_port_.c_str(),
                baud_rate_);
  }

  ~SmallCarBaseNode() override {
    // 节点退出时主动停车，避免进程异常结束后 MCU 继续保持最后一次运动命令。
    if (client_.IsOpen()) {
      client_.SendStop();
      client_.Close();
    }
  }

 private:
  /** 声明串口、话题、传感器、协方差和舵机映射参数。 */
  void DeclareParameters() {
    declare_parameter<std::string>("serial_port", "/dev/small_car_mcu");
    declare_parameter<int>("baud_rate", 115200);
    declare_parameter<std::string>("chassis_config", "");
    declare_parameter<int>("cmd_vel_timeout_ms", 500);
    declare_parameter<double>("command_rate_hz", 20.0);
    declare_parameter<std::string>(
        "mcu_recovery_request",
        "/workspace/smart_car/robot_host/runtime/mcu_recovery.request");
    declare_parameter<std::string>("cmd_vel_topic", "");
    declare_parameter<std::string>("servo_trajectory_topic", "");
    declare_parameter<std::string>("wheel_odom_raw_topic", "");
    declare_parameter<std::string>("imu_data_raw_topic", "");
    declare_parameter<std::string>("ultrasonic_front_topic", "");
    declare_parameter<std::string>("joint_states_topic", "");
    declare_parameter<std::string>("diagnostics_topic", "");
    declare_parameter<std::string>("odom_frame", "odom");
    declare_parameter<std::string>("base_frame", "base_link");
    declare_parameter<std::string>("imu_frame", "imu_link");
    declare_parameter<std::string>("ultrasonic_frame", "ultrasonic_link");
    declare_parameter<bool>("publish_joint_states", true);
    declare_parameter<double>("wheel_radius_m", 0.0325);
    declare_parameter<double>("ultrasonic_min_range_m", 0.02);
    declare_parameter<double>("ultrasonic_max_range_m", 4.0);
    declare_parameter<double>("ultrasonic_field_of_view_rad", 0.52);
    declare_parameter<int>("ultrasonic_filter_window", 5);
    declare_parameter<double>("odom_linear_velocity_variance", 0.04);
    declare_parameter<double>("odom_angular_velocity_variance", 0.05);
    declare_parameter<double>("imu_acceleration_variance", 0.1);
    declare_parameter<double>("imu_angular_velocity_variance", 0.02);
    DeclareServoParameters("upper", 1500, 800, 2300);
    DeclareServoParameters("lower", 1250, 800, 1700);
  }

  /** 为左右舵机声明一组同结构参数，前缀由 name 区分。 */
  void DeclareServoParameters(const std::string& name, int center, int minimum,
                              int maximum) {
    declare_parameter<int>(name + "_servo_center_us", center);
    declare_parameter<int>(name + "_servo_min_us", minimum);
    declare_parameter<int>(name + "_servo_max_us", maximum);
    declare_parameter<double>(name + "_servo_range_rad", kPi);
    declare_parameter<double>(name + "_servo_sign", 1.0);
  }

  /** 启动时读取全部参数，并验证影响单位换算的比例值必须为正。 */
  void ReadParameters() {
    serial_port_ = get_parameter("serial_port").as_string();
    baud_rate_ = static_cast<int>(get_parameter("baud_rate").as_int());
    chassis_config_ = get_parameter("chassis_config").as_string();
    if (chassis_config_.empty()) {
      chassis_config_ =
          ament_index_cpp::get_package_share_directory("small_car_base") +
          "/config/chassis.yaml";
    }
    chassis_parameters_ = small_car::LoadChassisConfig(chassis_config_);
    DeclareRuntimeChassisParameters();
    max_linear_speed_mps_ =
        static_cast<double>(small_car::ChassisParameterValue(
            chassis_parameters_, "max_linear_speed_mm_s")) /
        1000.0;
    max_angular_speed_rad_s_ =
        static_cast<double>(small_car::ChassisParameterValue(
            chassis_parameters_, "max_angular_speed_mrad_s")) /
        1000.0;
    front_stop_distance_m_ =
        static_cast<double>(small_car::ChassisParameterValue(
            chassis_parameters_, "ultra_near_distance_mm")) /
        1000.0;
    millimeters_per_tick_ =
        static_cast<double>(small_car::ChassisParameterValue(
            chassis_parameters_, "odom_mm_per_tick_num")) /
        kEncoderMillimeterDenominator;
    wheel_track_m_ =
        static_cast<double>(small_car::ChassisParameterValue(
            chassis_parameters_, "wheel_track_mm")) /
        1000.0;
    gyro_lsb_per_dps_ =
        static_cast<double>(small_car::ChassisParameterValue(
            chassis_parameters_, "gyro_lsb_per_dps_x10")) /
        10.0;
    cmd_vel_timeout_ =
        std::chrono::milliseconds(get_parameter("cmd_vel_timeout_ms").as_int());
    command_rate_hz_ = get_parameter("command_rate_hz").as_double();
    mcu_recovery_request_ = get_parameter("mcu_recovery_request").as_string();
    cmd_vel_topic_ = get_parameter("cmd_vel_topic").as_string();
    servo_trajectory_topic_ = get_parameter("servo_trajectory_topic").as_string();
    wheel_odom_raw_topic_ = get_parameter("wheel_odom_raw_topic").as_string();
    imu_data_raw_topic_ = get_parameter("imu_data_raw_topic").as_string();
    ultrasonic_front_topic_ = get_parameter("ultrasonic_front_topic").as_string();
    joint_states_topic_ = get_parameter("joint_states_topic").as_string();
    diagnostics_topic_ = get_parameter("diagnostics_topic").as_string();
    odom_frame_ = get_parameter("odom_frame").as_string();
    base_frame_ = get_parameter("base_frame").as_string();
    imu_frame_ = get_parameter("imu_frame").as_string();
    ultrasonic_frame_ = get_parameter("ultrasonic_frame").as_string();
    publish_joint_states_ = get_parameter("publish_joint_states").as_bool();
    wheel_radius_m_ = get_parameter("wheel_radius_m").as_double();
    ultra_min_m_ = get_parameter("ultrasonic_min_range_m").as_double();
    ultra_max_m_ = get_parameter("ultrasonic_max_range_m").as_double();
    ultra_fov_rad_ = get_parameter("ultrasonic_field_of_view_rad").as_double();
    const auto ultrasonic_filter_window =
        get_parameter("ultrasonic_filter_window").as_int();
    if (ultrasonic_filter_window <= 0 || ultrasonic_filter_window > 31 ||
        ultrasonic_filter_window % 2 == 0) {
      throw std::runtime_error(
          "ultrasonic_filter_window must be an odd integer in [1, 31]");
    }
    ultrasonic_filter_window_ =
        static_cast<std::size_t>(ultrasonic_filter_window);
    odom_linear_velocity_variance_ =
        get_parameter("odom_linear_velocity_variance").as_double();
    odom_angular_velocity_variance_ =
        get_parameter("odom_angular_velocity_variance").as_double();
    imu_acceleration_variance_ = get_parameter("imu_acceleration_variance").as_double();
    imu_angular_velocity_variance_ =
        get_parameter("imu_angular_velocity_variance").as_double();
    upper_servo_mapping_ = ReadServoParameters("upper");
    lower_servo_mapping_ = ReadServoParameters("lower");

    if (max_linear_speed_mps_ <= 0.0 || max_angular_speed_rad_s_ <= 0.0 ||
        command_rate_hz_ <= 0.0 || wheel_radius_m_ <= 0.0 ||
        millimeters_per_tick_ <= 0.0 || wheel_track_m_ <= 0.0 ||
        cmd_vel_topic_.empty() || servo_trajectory_topic_.empty() ||
        wheel_odom_raw_topic_.empty() || imu_data_raw_topic_.empty() ||
        ultrasonic_front_topic_.empty() || joint_states_topic_.empty() ||
        diagnostics_topic_.empty()) {
      throw std::runtime_error("ROS2 bridge contains a non-positive scale parameter");
    }
  }

  /** 从 chassis.yaml 注册全部可在线标定的底盘参数。 */
  void DeclareRuntimeChassisParameters() {
    for (auto& parameter : chassis_parameters_) {
      if (!small_car::IsRuntimeTunableChassisParameter(parameter.name)) {
        continue;
      }
      const auto value = declare_parameter<std::int64_t>(
          parameter.name, static_cast<std::int64_t>(parameter.value));
      if (value < std::numeric_limits<std::int32_t>::min() ||
          value > std::numeric_limits<std::int32_t>::max()) {
        throw std::runtime_error("runtime chassis parameter is outside int32: " +
                                 parameter.name);
      }
      std::string error;
      const auto validated = small_car::MakeChassisParameter(
          parameter.name, static_cast<std::int32_t>(value), &error);
      if (!validated.has_value()) {
        throw std::runtime_error(error);
      }
      parameter.value = validated->value;
    }
  }

  /** 读取一组舵机参数并检查 min <= center <= max。 */
  small_car::ServoMapping ReadServoParameters(const std::string& name) {
    small_car::ServoMapping result;
    result.center_us = static_cast<int>(get_parameter(name + "_servo_center_us").as_int());
    result.min_us = static_cast<int>(get_parameter(name + "_servo_min_us").as_int());
    result.max_us = static_cast<int>(get_parameter(name + "_servo_max_us").as_int());
    result.range_rad = get_parameter(name + "_servo_range_rad").as_double();
    result.sign = get_parameter(name + "_servo_sign").as_double();
    if (result.min_us > result.center_us || result.center_us > result.max_us ||
        result.range_rad <= 0.0) {
      throw std::runtime_error("invalid " + name + " servo mapping");
    }
    return result;
  }

  /** 打开桥接节点独占的 MCU 串口，失败时阻止节点继续启动。 */
  void OpenController() {
    if (!client_.Open(serial_port_, baud_rate_)) {
      throw std::runtime_error("cannot open serial port: " + serial_port_);
    }
  }

  /** 从 YAML 加载参数并逐项写入 MCU；失败时保留桥接功能用于现场排查。 */
  void ApplyControllerConfig() {
    std::string error;
    if (!small_car::ApplyChassisConfig(&client_, chassis_parameters_,
                                       std::chrono::milliseconds(500), &error)) {
      /*
       * 参数下发失败不能阻止 ROS2 bridge 启动。
       * 串口链路偶尔会因为 MCU 正在连续上报数据而错过参数回读，此时传感器发布、
       * cmd_vel 控制和后续手动重试仍然应该可用。
       */
      RCLCPP_WARN(get_logger(), "chassis config not verified: %s", error.c_str());
      return;
    }
    RCLCPP_INFO(get_logger(), "applied and verified %zu chassis parameters",
                chassis_parameters_.size());
  }

  /**
   * 创建全部 ROS 发布、订阅、服务和定时器。
   *
   * 5 ms 定时器负责尽快清空串口上行数据；command_rate_hz 定时器负责维持
   * 下行速度或心跳，两者分开避免传感器处理拖慢安全停车。
   */
  void CreateRosInterfaces() {
    wheel_odom_pub_ = create_publisher<nav_msgs::msg::Odometry>(wheel_odom_raw_topic_, 10);
    imu_raw_pub_ = create_publisher<sensor_msgs::msg::Imu>(
        imu_data_raw_topic_, rclcpp::SensorDataQoS());
    // 超声波消息体小且频率低，使用可靠 QoS 方便 RQt 默认订阅；
    // Nav2 的 BEST_EFFORT 订阅仍可兼容 RELIABLE 发布端。
    const auto ultrasonic_qos =
        rclcpp::QoS(rclcpp::KeepLast(10)).reliable().durability_volatile();
    range_pub_ = create_publisher<sensor_msgs::msg::Range>(
        ultrasonic_front_topic_, ultrasonic_qos);
    if (publish_joint_states_) {
      joint_pub_ =
          create_publisher<sensor_msgs::msg::JointState>(joint_states_topic_, 10);
    }
    diagnostics_pub_ = create_publisher<diagnostic_msgs::msg::DiagnosticArray>(diagnostics_topic_, 10);

    cmd_vel_sub_ = create_subscription<geometry_msgs::msg::TwistStamped>(
        cmd_vel_topic_, 10,
        std::bind(&SmallCarBaseNode::OnCmdVel, this, std::placeholders::_1));
    servo_sub_ = create_subscription<trajectory_msgs::msg::JointTrajectory>(
        servo_trajectory_topic_, 10,
        std::bind(&SmallCarBaseNode::OnServoTrajectory, this,
                  std::placeholders::_1));
    parameter_callback_handle_ = add_on_set_parameters_callback(
        std::bind(&SmallCarBaseNode::OnSetParameters, this,
                  std::placeholders::_1));

    poll_timer_ = create_wall_timer(std::chrono::milliseconds(5),
                                    std::bind(&SmallCarBaseNode::PollController, this));
    const auto period = std::chrono::duration<double>(1.0 / command_rate_hz_);
    command_timer_ = create_wall_timer(
        std::chrono::duration_cast<std::chrono::nanoseconds>(period),
        std::bind(&SmallCarBaseNode::MaintainCommand, this));
  }

  /** 根据启用的 ROS 发布项配置 MCU，关闭无消费者的周期遥测以节省串口带宽。 */
  void ConfigureTelemetry() {
    std::uint16_t mask =
        small_car::kTelemetryChassis | small_car::kTelemetryEncoder |
        small_car::kTelemetryImu | small_car::kTelemetryDevice;
    if (!client_.SendTelemetryConfig(mask)) {
      RCLCPP_WARN(get_logger(), "failed to configure MCU telemetry");
    }
  }

  /** 接收 Nav2 最终速度；无时间戳、过期或来自未来的命令触发立即停车。 */
  void OnCmdVel(const geometry_msgs::msg::TwistStamped::SharedPtr message) {
    const rclcpp::Time stamp(message->header.stamp);
    const double age_s = (now() - stamp).seconds();
    const auto received_at = std::chrono::steady_clock::now();
    if (stamp.nanoseconds() == 0 || age_s < -0.1 ||
        age_s > std::chrono::duration<double>(cmd_vel_timeout_).count()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                           "rejected stale or invalid velocity command; "
                           "forcing stop");
      // 不能继续保留上一条有效速度，否则安全节点的停车命令异常时车辆会延迟停车。
      command_safety_->SetCommand({}, received_at);
      SendSafeCommand(command_safety_->Evaluate(received_at));
      return;
    }

    command_safety_->SetCommand(
        {message->twist.linear.x, message->twist.angular.z}, received_at);
    SendSafeCommand(command_safety_->Evaluate(received_at));
  }

  void SendSafeCommand(const small_car::SafeCommand& command) {
    linear_command_mm_s_ =
        ToMilliUnits(command.velocity.linear_mps, max_linear_speed_mps_);
    angular_command_mrad_s_ =
        ToMilliUnits(command.velocity.angular_rad_s,
                     max_angular_speed_rad_s_);
    last_control_send_ok_ =
        client_.SendDrive(linear_command_mm_s_, angular_command_mrad_s_);
    if (!last_control_send_ok_) {
      RequestMcuRecovery();
    }
  }

  /** 将 SI 单位浮点数限幅并转换为协议使用的千分之一单位。 */
  static std::int16_t ToMilliUnits(double value, double maximum) {
    const double limited = std::clamp(value, -maximum, maximum);
    return static_cast<std::int16_t>(std::lround(limited * 1000.0));
  }

  /**
   * 周期维持速度命令和失联停车。
   *
   * 有新速度时重复发送以满足 MCU 看门狗；命令超时后发送一次 Stop；完全空闲时
   * 降频发送心跳，兼顾链路检测和 USB 稳定性。
   */
  void MaintainCommand() {
    const auto now = std::chrono::steady_clock::now();
    const auto command = command_safety_->Evaluate(now);
    if (command.state == small_car::CommandState::kIdle) {
      /*
       * 空闲心跳只需维持链路诊断，不需要跟随 20 Hz 控制定时器发送。
       * 降低小包频率可避免 CH9102 经 USB Hub 长时间写入时触发 xHCI 端点异常。
       */
      if (now - last_heartbeat_time_ >= idle_heartbeat_interval_) {
        last_control_send_ok_ = client_.SendHeartbeat();
        last_heartbeat_time_ = now;
      }
    } else if (command.state == small_car::CommandState::kTimedOut) {
      last_control_send_ok_ = client_.SendStop();
      last_heartbeat_time_ = now;
    } else {
      SendSafeCommand(command);
    }
  }

  /** 请求宿主机恢复 USB 映射；冷却时间防止故障时反复重建容器。 */
  void RequestMcuRecovery() {
    /*
     * 容器没有复位宿主机 USB 的权限。这里只写入一个请求文件，由宿主机
     * systemd.path 触发恢复脚本，避免给 ROS2 容器开放 Docker 或 sysfs 权限。
     */
    const auto now = std::chrono::steady_clock::now();
    if (mcu_recovery_request_.empty() ||
        now - last_recovery_request_time_ < recovery_request_cooldown_) {
      return;
    }

    std::ofstream request(mcu_recovery_request_, std::ios::trunc);
    if (!request) {
      RCLCPP_ERROR(get_logger(), "cannot create MCU recovery request: %s",
                   mcu_recovery_request_.c_str());
      return;
    }
    request << "cmd_vel serial write failed\n";
    last_recovery_request_time_ = now;
    RCLCPP_ERROR(get_logger(), "MCU link failed; USB recovery requested");
  }

  /** 解析 JointTrajectory 第一轨迹点，只更新其中明确给出的上下云台关节。 */
  void OnServoTrajectory(
      const trajectory_msgs::msg::JointTrajectory::SharedPtr message) {
    if (message->points.empty()) {
      return;
    }
    const auto& positions = message->points.front().positions;
    if (positions.size() != message->joint_names.size()) {
      RCLCPP_WARN(get_logger(), "servo trajectory has inconsistent joint data");
      return;
    }

    bool found = false;
    for (std::size_t index = 0; index < message->joint_names.size(); ++index) {
      if (message->joint_names[index] == "upper_servo_joint") {
        gimbal_->SetUpper(positions[index]);
        found = true;
      } else if (message->joint_names[index] == "lower_servo_joint") {
        gimbal_->SetLower(positions[index]);
        found = true;
      }
    }
    if (found) {
      const auto pulse = gimbal_->pulse();
      client_.SendServo(pulse.upper_us, pulse.lower_us);
      if (publish_joint_states_) {
        PublishJointState(now());
      }
    }
  }

  /** 同步处理一项易变参数；MCU 回读一致后才允许 ROS 参数值更新。 */
  rcl_interfaces::msg::SetParametersResult OnSetParameters(
      const std::vector<rclcpp::Parameter>& parameters) {
    rcl_interfaces::msg::SetParametersResult result;
    result.successful = true;

    const auto tunable_count = static_cast<std::size_t>(std::count_if(
        parameters.begin(), parameters.end(), [](const auto& parameter) {
          return small_car::IsRuntimeTunableChassisParameter(
              parameter.get_name());
        }));
    if (tunable_count == 0) {
      return result;
    }
    if (tunable_count != 1) {
      result.successful = false;
      result.reason = "set one runtime chassis parameter at a time";
      return result;
    }

    const auto iterator = std::find_if(
        parameters.begin(), parameters.end(), [](const auto& parameter) {
          return small_car::IsRuntimeTunableChassisParameter(
              parameter.get_name());
        });
    if (iterator->get_type() != rclcpp::ParameterType::PARAMETER_INTEGER) {
      result.successful = false;
      result.reason = iterator->get_name() + " requires an integer value";
      return result;
    }

    const auto value = iterator->as_int();
    if (value < std::numeric_limits<std::int32_t>::min() ||
        value > std::numeric_limits<std::int32_t>::max()) {
      result.successful = false;
      result.reason = iterator->get_name() + " is outside int32 range";
      return result;
    }

    std::string error;
    const auto parameter = small_car::MakeChassisParameter(
        iterator->get_name(), static_cast<std::int32_t>(value), &error);
    if (!parameter.has_value()) {
      result.successful = false;
      result.reason = error;
      return result;
    }

    std::int32_t actual = 0;
    if (!small_car::ApplyChassisParameter(
            &client_, *parameter, std::chrono::milliseconds(800), &actual,
            &error)) {
      result.successful = false;
      result.reason = error;
      return result;
    }

    for (auto& loaded : chassis_parameters_) {
      if (loaded.id == parameter->id) {
        loaded.value = actual;
        break;
      }
    }
    ApplyHostChassisParameter(parameter->name, actual);
    RCLCPP_INFO(get_logger(), "runtime chassis parameter applied: %s=%d",
                parameter->name.c_str(), actual);
    return result;
  }

  /** 同步刷新上位机参与单位换算和安全限幅的底盘参数。 */
  void ApplyHostChassisParameter(const std::string& name, std::int32_t value) {
    if (name == "odom_mm_per_tick_num") {
      millimeters_per_tick_ =
          static_cast<double>(value) / kEncoderMillimeterDenominator;
    } else if (name == "wheel_track_mm") {
      wheel_track_m_ = static_cast<double>(value) / 1000.0;
    } else if (name == "gyro_lsb_per_dps_x10") {
      gyro_lsb_per_dps_ = static_cast<double>(value) / 10.0;
    } else if (name == "ultra_near_distance_mm") {
      front_stop_distance_m_ = static_cast<double>(value) / 1000.0;
      command_safety_->SetFrontStopDistance(front_stop_distance_m_);
    } else if (name == "max_linear_speed_mm_s") {
      max_linear_speed_mps_ = static_cast<double>(value) / 1000.0;
      command_safety_->SetLimits(max_linear_speed_mps_,
                                 max_angular_speed_rad_s_);
    } else if (name == "max_angular_speed_mrad_s") {
      max_angular_speed_rad_s_ = static_cast<double>(value) / 1000.0;
      command_safety_->SetLimits(max_linear_speed_mps_,
                                 max_angular_speed_rad_s_);
    }
  }

  /** 高频串口轮询入口；每次轮询后尝试发布所有已经更新的消息类型。 */
  void PollController() {
    client_.Poll();
    PublishWheelOdometry();
    PublishImu();
    PublishRange();
    PublishDiagnostics();
  }

  /** 将累计编码器计数换算为未融合的轮式速度里程计。 */
  void PublishWheelOdometry() {
    const auto value = client_.GetEncoderCounts();
    if (!value.has_value() || value->mcu_time_ms == last_encoder_time_ms_) {
      return;
    }
    last_encoder_time_ms_ = value->mcu_time_ms;
    if (!previous_encoder_counts_.has_value()) {
      previous_encoder_counts_ = value;
      return;
    }

    const auto previous = *previous_encoder_counts_;
    previous_encoder_counts_ = value;
    const std::uint32_t elapsed_ms =
        value->mcu_time_ms - previous.mcu_time_ms;
    if (elapsed_ms == 0U || elapsed_ms > kMaximumEncoderIntervalMs) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                           "encoder timestamp reset or gap; rebasing counts");
      return;
    }

    const std::int32_t delta_a =
        CounterDelta(value->count_a, previous.count_a);
    const std::int32_t delta_b =
        CounterDelta(value->count_b, previous.count_b);
    const std::int32_t delta_c =
        CounterDelta(value->count_c, previous.count_c);
    const std::int32_t delta_d =
        CounterDelta(value->count_d, previous.count_d);
    for (const auto delta : {delta_a, delta_b, delta_c, delta_d}) {
      if (std::abs(static_cast<std::int64_t>(delta)) >
          kMaximumEncoderDelta) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                             "encoder count jump rejected");
        return;
      }
    }

    const double left_ticks =
        (static_cast<double>(delta_a) + delta_b) * 0.5;
    const double right_ticks =
        (-static_cast<double>(delta_c) - delta_d) * 0.5;
    const double left_distance_m =
        left_ticks * millimeters_per_tick_ / 1000.0;
    const double right_distance_m =
        right_ticks * millimeters_per_tick_ / 1000.0;
    const double elapsed_s = elapsed_ms / 1000.0;
    left_wheel_speed_rad_s_ =
        left_distance_m / elapsed_s / wheel_radius_m_;
    right_wheel_speed_rad_s_ =
        right_distance_m / elapsed_s / wheel_radius_m_;
    left_wheel_position_rad_ += left_distance_m / wheel_radius_m_;
    right_wheel_position_rad_ += right_distance_m / wheel_radius_m_;

    nav_msgs::msg::Odometry message;
    message.header.stamp = now();
    message.header.frame_id = odom_frame_;
    message.child_frame_id = base_frame_;
    message.pose.pose.orientation.w = 1.0;
    for (const std::size_t index : {0U, 7U, 14U, 21U, 28U, 35U}) {
      message.pose.covariance[index] = 1.0e6;
    }
    message.twist.twist.linear.x =
        (left_distance_m + right_distance_m) * 0.5 / elapsed_s;
    message.twist.twist.linear.y = 0.0;
    message.twist.twist.angular.z =
        (right_distance_m - left_distance_m) / wheel_track_m_ / elapsed_s;
    message.twist.covariance[0] = odom_linear_velocity_variance_;
    message.twist.covariance[7] = odom_linear_velocity_variance_;
    message.twist.covariance[14] = 1.0e3;
    message.twist.covariance[21] = 1.0e3;
    message.twist.covariance[28] = 1.0e3;
    message.twist.covariance[35] = odom_angular_velocity_variance_;
    wheel_odom_pub_->publish(message);

    if (publish_joint_states_) {
      PublishJointState(message.header.stamp);
    }
  }

  /**
   * 发布新的 IMU 数据。
   *
   * 原始加速度和角速度按当前 ICM20948 量程换算。MCU 不提供姿态，
   * orientation_covariance[0] 设为 -1 供消费者明确忽略 orientation。
   */
  void PublishImu() {
    const auto value = client_.GetImuRaw();
    if (!value.has_value() || value->mcu_time_ms == last_imu_time_ms_) {
      return;
    }
    last_imu_time_ms_ = value->mcu_time_ms;
    sensor_msgs::msg::Imu raw;
    raw.header.stamp = now();
    raw.header.frame_id = imu_frame_;
    raw.orientation_covariance[0] = -1.0;
    raw.linear_acceleration.x = value->ax / 2048.0 * kGravity;
    raw.linear_acceleration.y = value->ay / 2048.0 * kGravity;
    raw.linear_acceleration.z = value->az / 2048.0 * kGravity;
    raw.angular_velocity.x = value->gx / gyro_lsb_per_dps_ * kDegreesToRadians;
    raw.angular_velocity.y = value->gy / gyro_lsb_per_dps_ * kDegreesToRadians;
    raw.angular_velocity.z = value->gz / gyro_lsb_per_dps_ * kDegreesToRadians;
    for (const std::size_t index : {0U, 4U, 8U}) {
      raw.linear_acceleration_covariance[index] = imu_acceleration_variance_;
      raw.angular_velocity_covariance[index] = imu_angular_velocity_variance_;
    }
    imu_raw_pub_->publish(raw);
  }

  /** 将最近测距窗口取中值，抑制室内多径反射产生的孤立跳变。 */
  double FilterUltrasonicRange(double range_m) {
    ultrasonic_samples_->Write(&range_m, 1);
    std::vector<double> samples(ultrasonic_samples_->size());
    ultrasonic_samples_->CopyTo(samples.data(), samples.size());
    const auto middle = samples.begin() + samples.size() / 2;
    std::nth_element(samples.begin(), middle, samples.end());
    return *middle;
  }

  /** 发布经过中值滤波的有效超声测距，并更新内部安全模块。 */
  void PublishRange() {
    const auto value = client_.GetChassisStatus();
    if (!value.has_value() || value->mcu_time_ms == last_chassis_time_ms_) {
      return;
    }
    last_chassis_time_ms_ = value->mcu_time_ms;
    if (value->ultra_mm < 0) {
      ultrasonic_samples_->Clear();
      filtered_ultrasonic_m_.reset();
      command_safety_->SetFrontRange(0.0, false);
      return;
    }
    filtered_ultrasonic_m_ =
        FilterUltrasonicRange(value->ultra_mm / 1000.0);
    command_safety_->SetFrontRange(*filtered_ultrasonic_m_, true);
    sensor_msgs::msg::Range message;
    message.header.stamp = now();
    message.header.frame_id = ultrasonic_frame_;
    message.radiation_type = sensor_msgs::msg::Range::ULTRASOUND;
    message.field_of_view = static_cast<float>(ultra_fov_rad_);
    message.min_range = static_cast<float>(ultra_min_m_);
    message.max_range = static_cast<float>(ultra_max_m_);
    message.range = static_cast<float>(*filtered_ultrasonic_m_);
    range_pub_->publish(message);
  }

  /** 合并轮子积分位置、轮速和当前舵机角度，发布完整 JointState。 */
  void PublishJointState(const rclcpp::Time& stamp) {
    sensor_msgs::msg::JointState message;
    message.header.stamp = stamp;
    message.name = {"front_left_wheel_joint", "rear_left_wheel_joint",
                    "front_right_wheel_joint", "rear_right_wheel_joint",
                    "upper_servo_joint", "lower_servo_joint"};
    const auto& gimbal_command = gimbal_->command();
    message.position = {left_wheel_position_rad_, left_wheel_position_rad_,
                        right_wheel_position_rad_, right_wheel_position_rad_,
                        gimbal_command.upper_rad, gimbal_command.lower_rad};
    message.velocity.assign(message.name.size(), 0.0);
    message.velocity[0] = left_wheel_speed_rad_s_;
    message.velocity[1] = left_wheel_speed_rad_s_;
    message.velocity[2] = right_wheel_speed_rad_s_;
    message.velocity[3] = right_wheel_speed_rad_s_;
    joint_pub_->publish(message);
  }

  /** 汇总 MCU 外设、主机命令、串口写入和最近 ACK，发布标准诊断消息。 */
  void PublishDiagnostics() {
    const auto value = client_.GetDeviceStatus();
    if (!value.has_value() || value->mcu_time_ms == last_device_time_ms_) {
      return;
    }
    last_device_time_ms_ = value->mcu_time_ms;
    diagnostic_msgs::msg::DiagnosticArray array;
    array.header.stamp = now();
    diagnostic_msgs::msg::DiagnosticStatus status;
    status.name = "small_car/controller";
    status.hardware_id = "C30D_V2.2_STM32F407";
    status.level = value->error == 0
                       ? diagnostic_msgs::msg::DiagnosticStatus::OK
                       : diagnostic_msgs::msg::DiagnosticStatus::ERROR;
    status.message = value->error == 0 ? "controller ready" : "controller error";
    status.values = {
        DiagnosticValue("gamepad", value->pad_ok ? "connected" : "disconnected"),
        DiagnosticValue("imu", value->imu_ok ? "ready" : "error"),
        DiagnosticValue("ultrasonic", value->ultra_ok ? "ready" : "timeout"),
        DiagnosticValue("error_code", std::to_string(value->error)),
        DiagnosticValue("mcu_time_ms", std::to_string(value->mcu_time_ms)),
        DiagnosticValue("host_linear_mm_s", std::to_string(linear_command_mm_s_)),
        DiagnosticValue("host_angular_mrad_s",
                        std::to_string(angular_command_mrad_s_)),
        DiagnosticValue("serial_write", last_control_send_ok_ ? "ok" : "failed"),
    };

    const auto chassis = client_.GetChassisStatus();
    if (chassis.has_value()) {
      status.values.push_back(
          DiagnosticValue("control_source", std::to_string(chassis->source)));
      status.values.push_back(
          DiagnosticValue("control_enabled", chassis->enabled ? "true" : "false"));
      status.values.push_back(
          DiagnosticValue("control_value_type", std::to_string(chassis->value_type)));
      status.values.push_back(
          DiagnosticValue("mcu_forward_value", std::to_string(chassis->forward)));
      status.values.push_back(
          DiagnosticValue("mcu_turn_value", std::to_string(chassis->turn)));
      status.values.push_back(
          DiagnosticValue("ultrasonic_mm", std::to_string(chassis->ultra_mm)));
      if (filtered_ultrasonic_m_.has_value()) {
        status.values.push_back(DiagnosticValue(
            "ultrasonic_filtered_mm",
            std::to_string(*filtered_ultrasonic_m_ * 1000.0)));
      }
    }

    const auto ack = client_.GetLastAck();
    if (ack.has_value()) {
      status.values.push_back(
          DiagnosticValue("last_ack_msg", std::to_string(ack->ack_msg)));
      status.values.push_back(
          DiagnosticValue("last_ack_result", std::to_string(ack->result)));
    }
    array.status.push_back(std::move(status));
    diagnostics_pub_->publish(array);
  }

  // 串口客户端、设备路径和 ROS 坐标系名称。
  small_car::CarClient client_;
  std::string serial_port_;
  std::string chassis_config_;
  std::vector<small_car::ChassisParameter> chassis_parameters_;
  std::string odom_frame_;
  std::string base_frame_;
  std::string imu_frame_;
  std::string ultrasonic_frame_;
  std::string cmd_vel_topic_;
  std::string servo_trajectory_topic_;
  std::string wheel_odom_raw_topic_;
  std::string imu_data_raw_topic_;
  std::string ultrasonic_front_topic_;
  std::string joint_states_topic_;
  std::string diagnostics_topic_;
  int baud_rate_ = 115200;

  // ROS SI 单位与 MCU 整数协议之间的限幅、尺寸和测距参数。
  double max_linear_speed_mps_ = 0.6;
  double max_angular_speed_rad_s_ = 2.0;
  double command_rate_hz_ = 20.0;
  double front_stop_distance_m_ = 0.2;
  double millimeters_per_tick_ = 0.0;
  double wheel_track_m_ = 0.115;
  double gyro_lsb_per_dps_ = 16.4;
  double wheel_radius_m_ = 0.0325;
  double ultra_min_m_ = 0.02;
  double ultra_max_m_ = 4.0;
  double ultra_fov_rad_ = 0.52;
  std::size_t ultrasonic_filter_window_ = 5;

  // 发布给定位和融合算法的初始方差；后续应使用实测数据标定。
  double odom_linear_velocity_variance_ = 0.04;
  double odom_angular_velocity_variance_ = 0.05;
  double imu_acceleration_variance_ = 0.1;
  double imu_angular_velocity_variance_ = 0.02;

  // RViz 轮子动画所需的积分位置，以及可选发布项开关。
  double left_wheel_position_rad_ = 0.0;
  double right_wheel_position_rad_ = 0.0;
  double left_wheel_speed_rad_s_ = 0.0;
  double right_wheel_speed_rad_s_ = 0.0;
  bool publish_joint_states_ = true;

  // 下行命令超时、空闲心跳和 USB 恢复节流状态。
  std::chrono::milliseconds cmd_vel_timeout_{500};
  std::chrono::milliseconds idle_heartbeat_interval_{1000};
  std::chrono::seconds recovery_request_cooldown_{30};
  std::chrono::steady_clock::time_point last_heartbeat_time_{};
  std::chrono::steady_clock::time_point last_recovery_request_time_{};
  std::string mcu_recovery_request_;
  bool last_control_send_ok_ = true;
  std::int16_t linear_command_mm_s_ = 0;
  std::int16_t angular_command_mrad_s_ = 0;

  // 上下两路云台映射、命令安全模块和运行状态。
  small_car::ServoMapping upper_servo_mapping_;
  small_car::ServoMapping lower_servo_mapping_;
  std::unique_ptr<small_car::GimbalController> gimbal_;
  std::unique_ptr<small_car::CommandSafety> command_safety_;
  std::unique_ptr<small_car::RingBuffer<double>> ultrasonic_samples_;
  std::optional<double> filtered_ultrasonic_m_;

  // 各 MCU 消息最近时间戳用于去重；UINT*_MAX 表示尚未接收过。
  std::uint32_t last_encoder_time_ms_ = UINT32_MAX;
  std::uint32_t last_imu_time_ms_ = UINT32_MAX;
  std::uint32_t last_chassis_time_ms_ = UINT32_MAX;
  std::uint32_t last_device_time_ms_ = UINT32_MAX;
  std::optional<small_car::EncoderCounts> previous_encoder_counts_;

  // ROS 通信对象与定时器，生命周期均由节点统一管理。
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr wheel_odom_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_raw_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Range>::SharedPtr range_pub_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_pub_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr diagnostics_pub_;
  rclcpp::Subscription<geometry_msgs::msg::TwistStamped>::SharedPtr cmd_vel_sub_;
  rclcpp::Subscription<trajectory_msgs::msg::JointTrajectory>::SharedPtr servo_sub_;
  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr
      parameter_callback_handle_;
  rclcpp::TimerBase::SharedPtr poll_timer_;
  rclcpp::TimerBase::SharedPtr command_timer_;
};

}  // namespace small_car_base

int main(int argc, char** argv) {
  // 构造或运行异常会被记录为 FATAL，并以非零状态退出供 Docker 重启策略处理。
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<small_car_base::SmallCarBaseNode>());
  } catch (const std::exception& error) {
    RCLCPP_FATAL(rclcpp::get_logger("small_car_base"), "%s",
                 error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
