import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from nav2_common.launch import RewrittenYaml


def _load_topics() -> dict[str, str]:
    interface_share = get_package_share_directory("small_car_interfaces")
    contract_path = os.path.join(interface_share, "config", "interfaces.yaml")
    with open(contract_path, encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    entries = contract.get("topics", {}) if isinstance(contract, dict) else {}
    required = (
        "cmd_vel",
        "cmd_vel_smoothed",
        "nav_collision_state",
        "nav_front_stop_polygon",
        "nav_global_costmap",
        "nav_global_footprint",
        "nav_local_costmap",
        "nav_local_footprint",
        "odom",
        "ultrasonic_front",
    )
    result = {}
    for key in required:
        name = entries.get(key, {}).get("name")
        if not isinstance(name, str) or not name.startswith("/"):
            raise RuntimeError(f"invalid ROS interface topic: {key}")
        result[key] = name
    return result


def generate_launch_description():
    nav2_share = get_package_share_directory("nav2_bringup")
    car_nav2_share = get_package_share_directory("small_car_nav2")
    base_share = get_package_share_directory("small_car_base")
    gateway_share = get_package_share_directory("robot_tool_gateway")
    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")
    topics = _load_topics()
    configured_params = RewrittenYaml(
        source_file=params_file,
        param_rewrites={
            "cmd_vel_in_topic": topics["cmd_vel_smoothed"],
            "cmd_vel_out_topic": topics["cmd_vel"],
            "costmap_topic": topics["nav_local_costmap"],
            "footprint_topic": topics["nav_local_footprint"],
            "global_costmap_topic": topics["nav_global_costmap"],
            "global_footprint_topic": topics["nav_global_footprint"],
            "local_costmap_topic": topics["nav_local_costmap"],
            "local_footprint_topic": topics["nav_local_footprint"],
            "odom_topic": topics["odom"],
            "polygon_pub_topic": topics["nav_front_stop_polygon"],
            "state_topic": topics["nav_collision_state"],
            "topic": topics["ultrasonic_front"],
        },
        # RewrittenYaml 的 param_rewrites 只能生成标量。通过替换列表中的占位值，
        # 保留 RangeSensorLayer 所要求的 string_array 参数类型。
        value_rewrites={
            "__ULTRASONIC_FRONT_TOPIC__": topics["ultrasonic_front"],
        },
        convert_types=True,
    )

    base = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(base_share, "launch", "base.launch.py")
        ),
        launch_arguments={"use_sim_time": use_sim_time}.items(),
    )
    robot_tool_gateway = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(gateway_share, "launch", "gateway.launch.py")
        )
    )
    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_share, "launch", "navigation_launch.py")
        ),
        launch_arguments={
            "params_file": configured_params,
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
            default_value=os.path.join(car_nav2_share, "config", "nav2.yaml"),
        ),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        base,
        robot_tool_gateway,
        nav2_container,
        navigation,
    ])
