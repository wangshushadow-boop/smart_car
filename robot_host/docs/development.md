# 开发与测试

## 核心库

核心库不依赖 ROS，适合在 Linux/WSL 单独构建：

```bash
cd robot_host
cmake -S . -B build-host
cmake --build build-host -j
ctest --test-dir build-host --output-on-failure
```

新增业务能力时先放入 `core/small_car_base/<module>/`，再由 `ros/<package>/` 做消息转换。核心层不得包含 `rclcpp`、topic 或 ROS 参数代码。

## ROS 工作区

```bash
source /opt/ros/kilted/setup.bash
cd /workspace/smart_car
colcon --log-base robot_host/log-ros build \
  --base-paths ros_middleware/src robot_host/ros \
  --build-base robot_host/build-ros \
  --install-base robot_host/install-ros \
  --symlink-install
source robot_host/install-ros/setup.bash
```

只修改 launch、YAML、URDF 时仍建议重新执行 `colcon build`，保证安装空间同步。

## 变更规则

- 串口协议同时修改 `robot_host/core/small_car_base/protocol`、`small_car_f407/Core/Modules/Comm` 和 [协议文档](protocol.md)。
- 公共 ROS 消息只放在 `ros_middleware/src/small_car_interfaces`。
- 机器人节点、launch 和参数只放在 `robot_host/ros`。
- 标定结果写回 YAML，不依赖临时 `ros2 param set`。
- 提交前至少运行核心 CTest；协议改动还要构建固件 Debug 版本。

固件检查：

```bash
cd small_car_f407
cmake --preset Debug
cmake --build --preset Debug
```
