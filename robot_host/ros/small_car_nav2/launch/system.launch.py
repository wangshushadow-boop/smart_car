import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from launch_ros.parameter_descriptions import ParameterFile


def generate_launch_description():
    nav2_share = get_package_share_directory("nav2_bringup")
    car_nav2_share = get_package_share_directory("small_car_nav2")
    base_share = get_package_share_directory("small_car_base")

    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")
    configured_params = ParameterFile(params_file, allow_substs=True)

    base = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(base_share, "launch", "base.launch.py")
        ),
        launch_arguments={"use_sim_time": use_sim_time}.items(),
    )

    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_share, "launch", "navigation_launch.py")
        ),
        launch_arguments={
            "params_file": params_file,
            "use_sim_time": use_sim_time,
            "autostart": "True",
            "use_composition": "True",
            "container_name": "nav2_container",
            "use_respawn": "False",
        }.items(),
    )

    nav2_container = ComposableNodeContainer(
        name="nav2_container",
        namespace="",
        package="rclcpp_components",
        executable="component_container_isolated",
        parameters=[
            configured_params,
            {"autostart": True, "use_sim_time": use_sim_time},
        ],
        output="screen",
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(
                car_nav2_share, "config", "nav2.yaml"
            ),
        ),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        base,
        nav2_container,
        navigation,
    ])
