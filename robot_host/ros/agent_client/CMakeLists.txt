cmake_minimum_required(VERSION 3.16)
project(agent_client LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(small_car_interfaces REQUIRED)

set(ROBOT_HOST_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ROBOT_HOST_BUILD_CORE OFF CACHE BOOL "" FORCE)
set(ROBOT_HOST_BUILD_AUDIO ON CACHE BOOL "" FORCE)
add_subdirectory(
  ${CMAKE_CURRENT_SOURCE_DIR}/../../core
  ${CMAKE_CURRENT_BINARY_DIR}/robot_host_audio
)

add_executable(agent_client_node
  src/main.cpp
  src/agent_client_node.cpp
  src/agent_service_client.cpp
  src/camera_sampler.cpp
  src/response_player.cpp
  src/utterance_buffer.cpp
  src/voice_activity_detector.cpp
)
target_include_directories(agent_client_node PRIVATE include)
target_link_libraries(agent_client_node PRIVATE
  robot_host_audio
  rclcpp::rclcpp
  sensor_msgs::sensor_msgs_library
  ${small_car_interfaces_TARGETS}
)

install(TARGETS agent_client_node
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  enable_testing()
  add_executable(agent_client_media_buffer_test
    tests/media_buffer_test.cpp
    src/utterance_buffer.cpp
    src/voice_activity_detector.cpp
  )
  target_include_directories(agent_client_media_buffer_test PRIVATE include)
  target_include_directories(agent_client_media_buffer_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../../core
  )
  add_test(NAME agent_client_media_buffer_test
           COMMAND agent_client_media_buffer_test)

endif()

ament_package()
