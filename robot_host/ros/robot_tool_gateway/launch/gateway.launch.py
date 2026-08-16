import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def _load_contract():
    share = get_package_share_directory("small_car_interfaces")
    with open(os.path.join(share, "config", "interfaces.yaml"), encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def generate_launch_description():
    contract = _load_contract()
    actions = contract["actions"]
    topics = contract["topics"]
    return LaunchDescription([
        Node(
            package="robot_tool_gateway",
            executable="robot_tool_gateway_node",
            name="robot_tool_gateway",
            output="screen",
            parameters=[{
                "tool_action": actions["robot_tool_execute"]["name"],
                "drive_action": actions["nav_drive_on_heading"]["name"],
                "spin_action": actions["nav_spin"]["name"],
                "servo_topic": topics["servo_trajectory"]["name"],
                "image_topic": topics["camera_image_compressed"]["name"],
            }],
        )
    ])
