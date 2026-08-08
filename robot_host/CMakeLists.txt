cmake_minimum_required(VERSION 3.16)

project(robot_host LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(ROBOT_HOST_BUILD_TESTS "Build robot_host unit tests" ON)

if(ROBOT_HOST_BUILD_TESTS)
  enable_testing()
endif()

add_subdirectory(core)
