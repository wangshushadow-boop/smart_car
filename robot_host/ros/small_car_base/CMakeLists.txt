cmake_minimum_required(VERSION 3.16)
project(small_car_base LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(yaml-cpp REQUIRED)

set(ROBOT_HOST_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ROBOT_HOST_BUILD_CORE ON CACHE BOOL "" FORCE)
set(ROBOT_HOST_BUILD_AUDIO OFF CACHE BOOL "" FORCE)
add_subdirectory(
  ${CMAKE_CURRENT_SOURCE_DIR}/../../core
  ${CMAKE_CURRENT_BINARY_DIR}/robot_host_core
)

add_executable(small_car_base_node ros/base_node.cpp)
target_link_libraries(small_car_base_node PRIVATE
  robot_host_core
  ${diagnostic_msgs_TARGETS}
  ${geometry_msgs_TARGETS}
  ${nav_msgs_TARGETS}
  ${rcl_interfaces_TARGETS}
  ${sensor_msgs_TARGETS}
  ${trajectory_msgs_TARGETS}
  ament_index_cpp::ament_index_cpp
  rclcpp::rclcpp
  sensor_msgs::sensor_msgs_library
)

add_executable(odom_path_node ros/odom_path_node.cpp)
target_link_libraries(odom_path_node PRIVATE
  robot_host_core
  ${geometry_msgs_TARGETS}
  ${nav_msgs_TARGETS}
  rclcpp::rclcpp
)

install(TARGETS robot_host_core small_car_base_node odom_path_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY ../../core/small_car_base/
  DESTINATION include/small_car_base
  FILES_MATCHING PATTERN "*.hpp"
)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

ament_export_include_directories(include)
ament_export_libraries(robot_host_core)
ament_package()
