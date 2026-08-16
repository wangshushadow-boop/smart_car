cmake_minimum_required(VERSION 3.16)
project(robot_tool_gateway LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(small_car_interfaces REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(yaml-cpp REQUIRED)

add_executable(robot_tool_gateway_node src/robot_tool_gateway_node.cpp)
target_link_libraries(robot_tool_gateway_node PRIVATE
  yaml-cpp
  ${nav2_msgs_TARGETS}
  rclcpp::rclcpp
  rclcpp_action::rclcpp_action
  sensor_msgs::sensor_msgs_library
  ${small_car_interfaces_TARGETS}
  ${trajectory_msgs_TARGETS}
)

install(TARGETS robot_tool_gateway_node RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
