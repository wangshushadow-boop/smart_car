"""树莓派真实摄像头和 Jabra 麦克风 ROS 2 发布链路。"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
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
                    ("image_raw", "/car/camera/image_raw"),
                    ("camera_info", "/car/camera/camera_info"),
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
                    ("in", "/car/camera/image_raw"),
                    ("out/compressed", "/car/camera/image/compressed"),
                ],
                output="screen",
            ),
            Node(
                package="small_car_av",
                executable="jabra_audio_publisher",
                name="car_jabra_audio",
                parameters=[
                    {
                        "backend": "alsa",
                        "alsa_device": "plughw:CARD=USB,DEV=0",
                    }
                ],
                output="screen",
            ),
            Node(
                package="small_car_av",
                executable="jabra_audio_player",
                name="car_jabra_audio_player",
                parameters=[{"alsa_device": "plughw:CARD=USB,DEV=0"}],
                output="screen",
            ),
        ]
    )
