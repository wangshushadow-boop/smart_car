cmake_minimum_required(VERSION 3.16)

option(ROBOT_HOST_BUILD_CORE "Build the MCU and chassis core library" ON)
option(ROBOT_HOST_BUILD_AUDIO "Build the optional ALSA audio device library" OFF)

if(ROBOT_HOST_BUILD_CORE)
  find_package(yaml-cpp REQUIRED)
  add_library(robot_host_core
    small_car_base/chassis/chassis_config.cpp
    small_car_base/control/command_safety.cpp
    small_car_base/mcu/car_client.cpp
    small_car_base/protocol/protocol.cpp
    small_car_base/servo/gimbal_controller.cpp
    small_car_base/trajectory/path_accumulator.cpp
    small_car_base/transport/serial_port.cpp
  )
  target_compile_features(robot_host_core PUBLIC cxx_std_17)
  target_compile_definitions(robot_host_core PRIVATE _DEFAULT_SOURCE)
  target_include_directories(robot_host_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include>
  )
  target_link_libraries(robot_host_core PUBLIC yaml-cpp)
endif()

if(ROBOT_HOST_BUILD_AUDIO)
  find_package(ALSA REQUIRED)
  add_library(robot_host_audio small_car_base/audio/audio_device.cpp)
  target_compile_features(robot_host_audio PUBLIC cxx_std_17)
  target_compile_definitions(robot_host_audio PRIVATE _DEFAULT_SOURCE)
  target_include_directories(robot_host_audio PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include>
  )
  target_link_libraries(robot_host_audio PUBLIC ALSA::ALSA)
endif()

if(ROBOT_HOST_BUILD_TESTS AND ROBOT_HOST_BUILD_CORE)
  enable_testing()

  add_executable(protocol_test small_car_base/protocol/protocol_test.cpp)
  target_link_libraries(protocol_test PRIVATE robot_host_core)
  add_test(NAME protocol_test COMMAND protocol_test)

  add_executable(module_test small_car_base/control/module_test.cpp)
  target_link_libraries(module_test PRIVATE robot_host_core)
  add_test(NAME module_test COMMAND module_test)

  add_executable(ring_buffer_test
    small_car_base/buffer/ring_buffer_test.cpp
  )
  target_include_directories(ring_buffer_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
  )
  add_test(NAME ring_buffer_test COMMAND ring_buffer_test)

  add_executable(chassis_config_test
    small_car_base/chassis/chassis_config_test.cpp
  )
  target_link_libraries(chassis_config_test PRIVATE robot_host_core)
  add_test(
    NAME chassis_config_test
    COMMAND chassis_config_test
            ${CMAKE_CURRENT_SOURCE_DIR}/../ros/small_car_base/config/chassis.yaml
  )

  add_executable(path_accumulator_test
    small_car_base/trajectory/path_accumulator_test.cpp
  )
  target_link_libraries(path_accumulator_test PRIVATE robot_host_core)
  add_test(NAME path_accumulator_test COMMAND path_accumulator_test)
endif()
