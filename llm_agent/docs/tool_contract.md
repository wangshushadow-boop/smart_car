# Agent 工具契约

## 安全原则

模型只能请求工具，不能直接访问 `rclpy`、发布任意 topic 或构造底盘控制消息。只有 Agent Server
唯一 `ToolRegistry` 中的工具才能执行。生产环境的动作 Tool 通过 `RosRobotToolClient` 调用树莓派
`robot_tool_gateway`；Gateway Handler 不是第二套 Agent Tool 注册表，并会执行参数二次校验。

当前工具：

| 工具 | 类型 | 状态 |
| --- | --- | --- |
| `get_robot_status` | 只读 | 已注册；ROS 网关尚未接入时返回 `available=false` |
| `move_relative` | 实车动作 | 距离范围 -2～2 m，绝对值至少 0.05 m |
| `rotate_relative` | 实车动作 | 模型使用 `left/right`；下发时正数左转、负数右转 |
| `stop_motion` | 实车动作 | 请求树莓派取消当前 Nav2 Action |
| `set_camera_pan` | 实车动作 | 水平云台范围 -90～90° |
| `set_camera_tilt` | 实车动作 | 俯仰云台范围 -45～45° |
| `capture_camera` | 只读 | 返回树莓派缓存的最新压缩相机画面 |

生产环境动作 Tool 返回 `small_car.tool_result.v1`，表示树莓派已经真实执行；最终响应不再携带
`robot_task`，因此 `agent_client` 不会二次执行。没有注入 RobotToolClient 的离线单元测试仍保留
`small_car.motion.v1` 声明式兼容路径。Agent Server 始终不能发布速度或直接访问 Nav2。

所有动态 Skill 共用 `runtime/agent_loop.py`，执行“观察 → 决策 → 单个 Tool → 新观察”的循环。
Skill 只声明目标、工具白名单、任务说明和预算，不再为每种功能增加执行节点。每一步依次经过
`ToolPolicy`、唯一 `ToolRegistry` 和 Pi Gateway，不允许模型直接访问 ROS。

动态 Skill 位于 `llm_agent/skills/<skill_name>/SKILL.yaml`。Agent 启动时只扫描这一层目录，完成
Schema、模板参数、工具白名单和任务预算校验后自动注册；增加动态任务不需要新增 Python 文件。
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

例如“前进一米，然后右转九十度”由 `motion_sequence` Skill 产生：

```json
{
  "schema": "small_car.motion_sequence.v1",
  "skill": "motion_sequence",
  "steps": [
    {
      "schema": "small_car.motion.v1",
      "action": "move_relative",
      "distance_m": 1.0
    },
    {
      "schema": "small_car.motion.v1",
      "action": "rotate_relative",
      "angle_deg": -90.0
    }
  ]
}
```

树莓派客户端只接受 2～8 步，每一步继续遵守单步协议的范围和字段白名单，组合任务中不允许嵌入
`stop_motion`。需要停止时应发送独立停止请求，客户端会取消当前 Nav2 Action 并清空剩余步骤。

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
4. 确认 `prompts/agent_loop.txt` 中的通用决策约束仍覆盖该工具；
5. 添加合法、非法参数、超时和外部失败测试；
6. 动作工具还必须通过后续安全策略，并先在仿真环境验证。

禁止添加下列通用能力：

- `publish_any_topic`；
- `call_any_service`；
- 任意 shell 或 Python 执行；
- 无范围限制的速度、距离或持续时间参数。

真实车辆状态接入仍应通过受控的 `VehicleGateway` 实现，并从 `ros_middleware` 的共享接口契约读取
topic/service/action 名称。

## 新增 Skill 流程

1. 新建 `skills/<skill_name>/SKILL.yaml`；
2. 声明参数、目标模板、任务规则、`allowed_tools` 和预算；
3. 重启 Agent，由 Loader 自动扫描并校验；
4. 测试参数、工具权限、预算、取消和失败行为；
5. 只有新增原子硬件能力时才增加 Tool 和 Robot Gateway Handler。
