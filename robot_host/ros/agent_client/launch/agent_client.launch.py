"""树莓派摄像头和统一 C++ Agent Client 启动文件。"""

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def _load_interfaces() -> dict[str, str]:
    share = get_package_share_directory("small_car_interfaces")
    with open(os.path.join(share, "config", "interfaces.yaml"), encoding="utf-8") as stream:
        contract = yaml.safe_load(stream)
    topics = contract.get("topics", {})
    services = contract.get("services", {})
    values = {
        "agent_run": services.get("agent_run", {}).get("name"),
        "audio_enqueue": services.get("audio_enqueue", {}).get("name"),
        "camera_image_raw": topics.get("camera_image_raw", {}).get("name"),
        "camera_info": topics.get("camera_info", {}).get("name"),
        "camera_image_compressed": topics.get("camera_image_compressed", {}).get("name"),
    }
    if any(not isinstance(value, str) or not value.startswith("/") for value in values.values()):
        raise RuntimeError("Agent Client 所需 ROS 接口契约无效")
    return values


def generate_launch_description() -> LaunchDescription:
    interfaces = _load_interfaces()
    config = os.path.join(
        get_package_share_directory("agent_client"), "config", "agent_client.yaml"
    )
    return LaunchDescription(
        [
            Node(
                package="v4l2_camera",
                executable="v4l2_camera_node",
                name="car_camera",
                parameters=[
                    {
                        "video_device": "/dev/video0",
                        "pixel_format": "YUYV",
                        "output_encoding": "rgb8",
                        "image_size": [640, 480],
                        "time_per_frame": [1, 30],
                    }
                ],
                remappings=[
                    ("image_raw", interfaces["camera_image_raw"]),
                    ("camera_info", interfaces["camera_info"]),
                ],
                output="screen",
            ),
            Node(
                package="image_transport",
                executable="republish",
                name="car_image_republisher",
                parameters=[{"in_transport": "raw", "out_transport": "compressed"}],
                remappings=[
                    ("in", interfaces["camera_image_raw"]),
                    ("out/compressed", interfaces["camera_image_compressed"]),
                ],
                output="screen",
            ),
            Node(
                package="agent_client",
                executable="agent_client_node",
                name="car_agent_client",
                parameters=[
                    config,
                    {
                        "agent_service": interfaces["agent_run"],
                        "audio_service": interfaces["audio_enqueue"],
                        "image_topic": interfaces["camera_image_compressed"],
                    },
                ],
                output="screen",
            ),
        ]
    )
