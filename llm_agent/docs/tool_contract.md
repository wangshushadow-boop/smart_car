# Agent 工具契约

## 安全原则

模型只能请求工具，不能直接访问 `rclpy`、发布任意 topic 或构造底盘控制消息。只有注册进
`ToolRegistry` 的工具才能执行。工具注册表是程序白名单，提示词中的工具列表只是辅助约束。

当前工具：

| 工具 | 类型 | 状态 |
| --- | --- | --- |
| `get_robot_status` | 只读 | 已注册；ROS 网关尚未接入时返回 `available=false` |
| `move_relative` | 声明式动作 | 距离范围 -2～2 m，绝对值至少 0.05 m |
| `rotate_relative` | 声明式动作 | 模型使用 `left/right`；下发时正数左转、负数右转 |
| `stop_motion` | 声明式动作 | 请求树莓派取消当前 Nav2 Action |

动作工具只生成 `small_car.motion.v1` JSON，不在 Agent Server 发布速度或访问 Nav2。树莓派
`agent_client` 会拒绝未知字段和越界数值，再调用 Nav2 的 `DriveOnHeading` 或 `Spin` Action。
模型侧旋转参数使用显式 `direction` 和正数角度大小，工具层再转换为下发协议的带符号角度。解析器
优先接受标准 JSON，并通过 `ast.literal_eval` 安全兼容 MiniCPM 的单引号字典输出；不会执行模型代码。
旧输出只有在 `reason` 中包含唯一明确的“左转”或“右转”时才会补齐方向；方向缺失或矛盾时拒绝
执行，避免实车根据含糊的角度符号转向。

## 调用与结果

模型意图输出中的调用会转换为：

```json
{
  "name": "get_robot_status",
  "arguments": {}
}
```

例如“向前一米”最终产生：

```json
{
  "schema": "small_car.motion.v1",
  "action": "move_relative",
  "distance_m": 1.0
}
```

注册表返回统一结果：

```json
{
  "name": "get_robot_status",
  "success": true,
  "data": {
    "available": false,
    "motion_state": "unknown",
    "battery_percentage": null,
    "fault": null,
    "detail": "ROS 车辆状态网关尚未配置"
  },
  "error": null
}
```

这里 `success=true` 表示工具代码正常完成；真实状态是否可用由 `data.available` 表示。未知工具、参数
校验失败、异常或超时则返回 `success=false` 和非空 `error`。

## 实现约束

每个工具必须提供：

- 稳定且唯一的 `name`；
- 面向开发者的 `description`；
- Pydantic `arguments_model`；
- `execute(arguments, context)` 实现；
- 可选的 `timeout_seconds`，否则使用注册表默认值。

`ToolContext` 当前只暴露：

- `request_id`；
- 共享取消信号；
- 受控服务集合。

工具返回值必须是可 JSON 序列化的字典。声明式运动工具不读取 ROS，也不声称动作已经完成；执行结果
由树莓派 Nav2 客户端负责记录。

## 新增工具流程

1. 在对应领域目录定义严格的参数模型；
2. 实现工具并通过受控 gateway 访问外部系统；
3. 在应用装配处显式注册；
4. 更新 `prompts/intent.txt` 中允许的工具；
5. 添加合法、非法参数、超时和外部失败测试；
6. 动作工具还必须通过后续安全策略，并先在仿真环境验证。

禁止添加下列通用能力：

- `publish_any_topic`；
- `call_any_service`；
- 任意 shell 或 Python 执行；
- 无范围限制的速度、距离或持续时间参数。

真实车辆状态接入仍应通过受控的 `VehicleGateway` 实现，并从 `ros_middleware` 的共享接口契约读取
topic/service/action 名称。
