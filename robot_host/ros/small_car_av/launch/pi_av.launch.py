"""树莓派真实摄像头和 Jabra 麦克风 ROS 2 发布链路。"""

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def _load_topics() -> dict[str, str]:
    interface_share = get_package_share_directory("small_car_interfaces")
    contract_path = os.path.join(interface_share, "config", "interfaces.yaml")
    with open(contract_path, encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    topics = contract.get("topics", {}) if isinstance(contract, dict) else {}
    required = (
        "audio_input",
        "audio_output",
        "camera_image_raw",
        "camera_info",
        "camera_image_compressed",
    )
    result = {}
    for key in required:
        value = topics.get(key, {}).get("name")
        if not isinstance(value, str) or not value.startswith("/"):
            raise RuntimeError(f"invalid ROS interface topic: {key}")
        result[key] = value
    return result


def generate_launch_description() -> LaunchDescription:
    topics = _load_topics()
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
                    ("image_raw", topics["camera_image_raw"]),
                    ("camera_info", topics["camera_info"]),
                ],
                output="screen",
            ),
            Node(
                package="image_transport",
                executable="republish",
                name="car_image_republisher",
                parameters=[
                    {
                        "in_transport": "raw",
                        "out_transport": "compressed",
                        "ut.jpeg_quality": 75,
                        "ut.compressed.jpeg_quality": 75,
                    }
                ],
                remappings=[
                    ("in", topics["camera_image_raw"]),
                    ("out/compressed", topics["camera_image_compressed"]),
                ],
                output="screen",
            ),
            Node(
                package="small_car_av",
                executable="jabra_audio_publisher",
                name="car_jabra_audio",
                parameters=[
                    {
                        "alsa_device": "plughw:CARD=USB,DEV=0",
                        "input_topic": topics["audio_input"],
                    }
                ],
                output="screen",
            ),
            Node(
                package="small_car_av",
                executable="jabra_audio_player",
                name="car_jabra_audio_player",
                parameters=[
                    {
                        "alsa_device": "plughw:CARD=USB,DEV=0",
                        "output_topic": topics["audio_output"],
                    }
                ],
                output="screen",
            ),
        ]
    )
