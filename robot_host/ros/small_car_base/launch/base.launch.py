import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml


def _load_topics() -> dict[str, str]:
    interface_share = get_package_share_directory("small_car_interfaces")
    contract_path = os.path.join(interface_share, "config", "interfaces.yaml")
    with open(contract_path, encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    entries = contract.get("topics", {}) if isinstance(contract, dict) else {}
    required = (
        "cmd_vel",
        "servo_trajectory",
        "wheel_odom_raw",
        "imu_data_raw",
        "ultrasonic_front",
        "joint_states",
        "diagnostics",
        "odom",
        "ekf_filtered_output",
    )
    result = {}
    for key in required:
        name = entries.get(key, {}).get("name")
        if not isinstance(name, str) or not name.startswith("/"):
            raise RuntimeError(f"invalid ROS interface topic: {key}")
        result[key] = name
    return result


def generate_launch_description():
    share = get_package_share_directory("small_car_base")
    description_share = get_package_share_directory("small_car_description")
    default_base_config = os.path.join(share, "config", "base.yaml")
    default_chassis_config = os.path.join(share, "config", "chassis.yaml")
    default_ekf_config = os.path.join(share, "config", "ekf.yaml")
    topics = _load_topics()
    ekf_parameters = RewrittenYaml(
        source_file=LaunchConfiguration("ekf_config"),
        param_rewrites={
            "odom0": topics["wheel_odom_raw"],
            "imu0": topics["imu_data_raw"],
        },
        convert_types=True,
    )

    return LaunchDescription([
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("base_config", default_value=default_base_config),
        DeclareLaunchArgument(
            "chassis_config", default_value=default_chassis_config
        ),
        DeclareLaunchArgument("ekf_config", default_value=default_ekf_config),
        Node(
            package="small_car_base",
            executable="small_car_base_node",
            name="small_car_base",
            output="screen",
            parameters=[
                LaunchConfiguration("base_config"),
                {
                    "chassis_config": LaunchConfiguration("chassis_config"),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                    "cmd_vel_topic": topics["cmd_vel"],
                    "servo_trajectory_topic": topics["servo_trajectory"],
                    "wheel_odom_raw_topic": topics["wheel_odom_raw"],
                    "imu_data_raw_topic": topics["imu_data_raw"],
                    "ultrasonic_front_topic": topics["ultrasonic_front"],
                    "joint_states_topic": topics["joint_states"],
                    "diagnostics_topic": topics["diagnostics"],
                },
            ],
        ),
        Node(
            package="robot_localization",
            executable="ekf_node",
            name="ekf_filter_node",
            output="screen",
            parameters=[
                ekf_parameters,
                {"use_sim_time": LaunchConfiguration("use_sim_time")},
            ],
            remappings=[(topics["ekf_filtered_output"], topics["odom"])],
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(
                    description_share, "launch", "description.launch.py"
                )
            ),
            launch_arguments={
                "use_sim_time": LaunchConfiguration("use_sim_time")
            }.items(),
        ),
    ])
