# ROS 中间件

`ros_middleware` 只维护小车各模块共享的 ROS 2 通信契约和运行环境，不包含业务节点或业务启动文件。

## 目录

- `src/small_car_interfaces`：共享的 `.msg`、`.srv`、`.action` 和 `config/interfaces.yaml` 接口契约。
- `config`：DDS 等公共通信配置。
- `docker`：ROS 2 构建与运行环境。
- `docs`：Topic、Service、Action 和 QoS 契约。

上位机业务节点、参数及 launch 文件位于 `robot_host/ros`。Agent 只依赖这里发布的接口包，不依赖 `robot_host` 内部实现。

完整系统由 `robot_host/ros/small_car_nav2/launch/system.launch.py` 启动：

```bash
docker compose -f ros_middleware/docker/compose.yaml up --build -d
```
