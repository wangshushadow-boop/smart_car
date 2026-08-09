# Repository Guidelines

## Project Structure & Module Organization

This workspace contains five cooperating components:

- `small_car_f407/` is the STM32F407 firmware. Application code lives under
  `Core/Modules/<Area>/{Inc,Src}`; CubeMX startup and peripheral code is in
  `Core/Inc` and `Core/Src`. `Drivers/`, `Middlewares/`, and `USB_HOST/` contain
  vendor or generated code. Hardware notes are in `small_car_f407/docs/`.
- `robot_host/` is the Raspberry Pi host application. ROS-independent code is
  under `core/`, ROS business packages and launch files under `ros/`, and
  operational files under `tools/`, `scripts/`, and `systemd/`.
- `ros_middleware/` owns shared ROS interfaces, DDS configuration, and the ROS
  container environment. It must not contain business nodes or launch files.
- `llm_agent/` owns model serving and Agent behavior and communicates through
  the interfaces defined by `ros_middleware/`.
- `agent_debug_web/` is an independent ROS Action client for browser-based
  multimodal debugging. It must not import Agent runtime, graph, model, tool,
  or speech implementation modules.

Keep protocol changes synchronized between `Core/Modules/Comm` and
`robot_host/core/small_car_base/protocol`.

## Build, Test, and Development Commands

From `small_car_f407/`:

```powershell
cmake --preset Debug
cmake --build --preset Debug
```

Use the `Release` preset for size/performance checks. The ARM GCC toolchain,
CMake 3.22+, and Ninja are required.

From `robot_host/` on Linux/WSL:

```bash
cmake -S . -B build && cmake --build build
ctest --test-dir build --output-on-failure
```

For the ROS workspace, source ROS 2 Kilted and run the `colcon` command documented
in `robot_host/README.md`. Use
`docker compose -f ros_middleware/docker/compose.yaml up --build -d`
for the hardware-integrated container.

## Coding Style & Naming Conventions

Follow `small_car_f407/.clang-format`: Google style, 2 spaces, no tabs, and a
120-column limit. Firmware is C11; host code is C++17. Use `snake_case` for C
functions/locals, `UpperCamelCase` for C++ types/functions, and
`UPPER_SNAKE_CASE` for macros. Preserve existing HAL/CubeMX names. Put custom
changes to generated files only inside `USER CODE BEGIN/END` blocks, and do not
reformat vendor-generated files wholesale.

## Testing Guidelines

Host tests are dependency-light `*_test.cpp` executables registered with CTest.
Add focused tests beside the module they cover and include malformed/boundary
protocol cases. Run the host CTest suite and a firmware Debug build before every
submission. Hardware-facing changes should also document the board, connection,
and observed result; confirmed fixes belong in `small_car_f407/docs/qa.md`.

## Commit & Pull Request Guidelines

History uses short, imperative Chinese subjects such as `优化底盘yaml参数` and
`修复ROS与MCU双向通信链路`. Keep each commit limited to one feature or fix and
name the affected module or hardware interface. Pull requests should explain the
behavioral change, list verification commands and hardware tests, link relevant
issues, and call out `.ioc`, protocol, pinout, parameter, or launch-file changes.
Attach logs or screenshots when they make hardware or RViz behavior reviewable.
Never commit build directories, firmware binaries, maps, logs, or local IDE
configuration.
