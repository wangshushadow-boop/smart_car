import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory("small_car_base")
    description_share = get_package_share_directory("small_car_description")
    default_base_config = os.path.join(share, "config", "base.yaml")
    default_chassis_config = os.path.join(share, "config", "chassis.yaml")
    default_ekf_config = os.path.join(share, "config", "ekf.yaml")

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
                {"chassis_config": LaunchConfiguration("chassis_config")},
                {"use_sim_time": LaunchConfiguration("use_sim_time")},
            ],
        ),
        Node(
            package="robot_localization",
            executable="ekf_node",
            name="ekf_filter_node",
            output="screen",
            parameters=[
                LaunchConfiguration("ekf_config"),
                {"use_sim_time": LaunchConfiguration("use_sim_time")},
            ],
            remappings=[("odometry/filtered", "odom")],
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
