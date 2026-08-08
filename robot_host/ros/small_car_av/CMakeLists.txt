cmake_minimum_required(VERSION 3.16)
project(small_car_av LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(small_car_interfaces REQUIRED)
find_package(std_msgs REQUIRED)

set(ROBOT_HOST_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ROBOT_HOST_BUILD_CORE OFF CACHE BOOL "" FORCE)
set(ROBOT_HOST_BUILD_AUDIO ON CACHE BOOL "" FORCE)
add_subdirectory(
  ${CMAKE_CURRENT_SOURCE_DIR}/../../core
  ${CMAKE_CURRENT_BINARY_DIR}/robot_host_audio
)

add_executable(jabra_audio_publisher src/jabra_audio_publisher.cpp)
target_link_libraries(jabra_audio_publisher PRIVATE
  robot_host_audio
  rclcpp::rclcpp
  ${small_car_interfaces_TARGETS}
)

add_executable(jabra_audio_player src/jabra_audio_player.cpp)
target_link_libraries(jabra_audio_player PRIVATE
  robot_host_audio
  rclcpp::rclcpp
  ${small_car_interfaces_TARGETS}
  ${std_msgs_TARGETS}
)

install(TARGETS jabra_audio_publisher jabra_audio_player
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
  FILES_MATCHING PATTERN "*.launch.py"
)

ament_package()
