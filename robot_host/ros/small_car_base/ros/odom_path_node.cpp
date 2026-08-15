#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

#include <geometry_msgs/msg/pose_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <nav_msgs/msg/path.hpp>
#include <rclcpp/rclcpp.hpp>

#include "small_car_base/trajectory/path_accumulator.hpp"

class OdomPathNode final : public rclcpp::Node {
 public:
  OdomPathNode() : Node("odom_path") {
    declare_parameter<std::string>("odom_topic", "");
    declare_parameter<std::string>("path_topic", "");
    declare_parameter<int64_t>("max_points", 5000);
    declare_parameter<double>("min_distance_m", 0.02);

    const auto odom_topic = get_parameter("odom_topic").as_string();
    const auto path_topic = get_parameter("path_topic").as_string();
    const auto configured_max_points = get_parameter("max_points").as_int();
    min_distance_m_ = get_parameter("min_distance_m").as_double();
    if (odom_topic.empty() || path_topic.empty()) {
      throw std::runtime_error("odom_topic and path_topic must not be empty");
    }
    if (configured_max_points <= 0 || min_distance_m_ < 0.0) {
      throw std::runtime_error("max_points must be positive and min_distance_m non-negative");
    }
    path_ = std::make_unique<small_car::PathAccumulator>(
        static_cast<std::size_t>(configured_max_points), min_distance_m_);

    auto path_qos = rclcpp::QoS(rclcpp::KeepLast(1));
    path_qos.reliable().transient_local();
    path_pub_ = create_publisher<nav_msgs::msg::Path>(path_topic, path_qos);
    odom_sub_ = create_subscription<nav_msgs::msg::Odometry>(
        odom_topic, rclcpp::QoS(10),
        [this](nav_msgs::msg::Odometry::ConstSharedPtr message) { OnOdometry(*message); });
  }

 private:
  void OnOdometry(const nav_msgs::msg::Odometry& odometry) {
    if (!frame_id_.empty() && frame_id_ != odometry.header.frame_id) {
      RCLCPP_WARN(get_logger(), "odometry frame changed from %s to %s; clearing path",
                  frame_id_.c_str(), odometry.header.frame_id.c_str());
      path_->Clear();
    }
    frame_id_ = odometry.header.frame_id;

    const auto& source = odometry.pose.pose;
    small_car::TrajectoryPose pose;
    pose.x = source.position.x;
    pose.y = source.position.y;
    pose.z = source.position.z;
    pose.orientation_x = source.orientation.x;
    pose.orientation_y = source.orientation.y;
    pose.orientation_z = source.orientation.z;
    pose.orientation_w = source.orientation.w;
    pose.timestamp_ns = rclcpp::Time(odometry.header.stamp).nanoseconds();
    if (!path_->Add(pose)) {
      return;
    }

    nav_msgs::msg::Path path;
    path.header = odometry.header;
    path.poses.reserve(path_->poses().size());
    for (const auto& stored : path_->poses()) {
      geometry_msgs::msg::PoseStamped output;
      output.header.frame_id = frame_id_;
      output.header.stamp.sec = static_cast<std::int32_t>(stored.timestamp_ns / 1000000000LL);
      output.header.stamp.nanosec =
          static_cast<std::uint32_t>(stored.timestamp_ns % 1000000000LL);
      output.pose.position.x = stored.x;
      output.pose.position.y = stored.y;
      output.pose.position.z = stored.z;
      output.pose.orientation.x = stored.orientation_x;
      output.pose.orientation.y = stored.orientation_y;
      output.pose.orientation.z = stored.orientation_z;
      output.pose.orientation.w = stored.orientation_w;
      path.poses.push_back(std::move(output));
    }
    path_pub_->publish(path);
  }

  double min_distance_m_{0.02};
  std::string frame_id_;
  std::unique_ptr<small_car::PathAccumulator> path_;
  rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr path_pub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_sub_;
};

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<OdomPathNode>());
  rclcpp::shutdown();
  return 0;
}
