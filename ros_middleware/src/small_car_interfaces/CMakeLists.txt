cmake_minimum_required(VERSION 3.8)
project(small_car_interfaces)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AgentContent.msg"
  "msg/AgentRequest.msg"
  "msg/AgentResponse.msg"
  "msg/AgentProgress.msg"
  "action/RunAgent.action"
  DEPENDENCIES builtin_interfaces
)

install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
