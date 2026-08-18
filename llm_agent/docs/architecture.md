# Agent 架构

## 总体边界

`llm_agent` 采用面向单台机器人的精简 Gateway 架构。所有调用端使用统一
`/car/agent/run` ROS Service；内部生产路径为：

```text
树莓派语音 / Web Debug / CLI
              ↓
         AgentGateway
      幂等 + 同 Session 串行
              ↓
        DialogueLoop ──────── 普通对话立即返回
              │
              ▼
         TaskManager ──────── 取消、抢占、后台串行
              │
              ▼
         SkillRunner
              │
           Reactor
              │
       SkillRegistry / ToolPolicy
              │
         ToolRegistry
                          ↓
                  RobotToolClient
                          ↓
             树莓派 Robot Tool Gateway
                          ↓
                  ROS / Nav2 / MCU
```

Agent Server 不采集设备、不发布 `/cmd_vel`、不直接访问 Nav2。麦克风、相机
聚合和扬声器播放属于树莓派 `agent_client`；真实动作与硬限制属于
`robot_tool_gateway`。

## 模块职责

| 模块 | 单一职责 |
| --- | --- |
| `gateway/` | 请求幂等、同 Session 串行和 Runtime 生命周期 |
| `runtime/reactor.py` | 两个运行角色共用的单步模型决策与解析 |
| `runtime/dialogue_loop.py` | 一轮用户对话、任务提交和语音输出 |
| `runtime/task_manager.py` | 后台任务状态、取消、抢占和串行执行 |
| `runtime/skill_runner.py` | 单步、固定计划和动态 ReAct Skill 执行 |
| `runtime/runtime.py` | Runtime 边界、会话持久化与生产依赖装配 |
| `runtime/prompt_builder.py` | 组装请求、历史、Skill 和观察上下文 |
| `sessions/` | SQLite 对话、任务和执行事件持久化 |
| `skills/` | 固定计划 Skill、目录扫描和动态任务声明 |
| `tools/policy.py` | 工具授权、时间、步骤及运动预算 |
| `tools/registry.py` | 工具唯一注册、参数校验、超时和执行 |
| `models/` | 生成、ASR、TTS Provider 与能力声明 |
| `transport/ros/` | ROS Service/Action 与领域契约转换 |
| `app/` | 配置、依赖装配和进程生命周期 |

## 两个 ReAct 角色

入站附件首先按 `models.yaml` 的 `input` 属性做能力判断。主模型原生支持时直接
传入；否则按 `agent.yaml` 的 `modalities.input.audio/image/video.models` 有序回退并转换为
带来源标记的文字块。媒体超过限制、路由禁用或全部 Provider 失败都会显式终止
本轮，不允许静默丢弃。

DialogueLoop 每轮只做一次决策：直接回答、控制当前任务或提交新 Skill。长 Skill
交给 TaskManager 后立即返回，因此后台任务不会阻塞后续对话。SkillRunner 对动态
Skill 执行有界的“观察 → 决策 → 单个 Tool → 新观察”循环。

```json
{"type":"skill_call","skill_name":"capture_camera","arguments":{}}
```

```json
{"type":"skill_call","skill_name":"find_object","arguments":{"target_name":"水瓶"}}
```

```json
{"type":"final","status":"completed","answer":"已经找到水瓶。"}
```

原子 Skill 内部只执行一个 Tool；执行结果、错误和 Robot Gateway 返回的新图片
写入轨迹。新机器人任务会通过 TaskManager 协作取消并抢占旧任务，普通聊天和
状态询问不会改变正在运行的 Skill。

## Skill 与 Tool

动态 Skill 位于 `skills/<name>/SKILL.yaml`。启动时扫描并校验名称、参数模板、
工具白名单和任务预算；Prompt 展示当前允许 Skill 的名称与参数 Schema，选择后生成完整
`RobotTask`。增加动态任务不需要 Python 文件或 Graph 节点。

Tool 是强类型原子能力，只能在 `runtime/runtime.py` 注册一次。启动时会自动
生成同名的单步骤 Skill 视图，不复制 Tool 实现。复杂 Skill 内的有效工具集合为：

```text
全局 ToolRegistry ∩ Skill allowed_tools ∩ 请求 allow_tools ∩ ToolPolicy
```

Server 策略只能收紧权限。距离、旋转、舵机角度、Nav2 超时和急停仍由树莓派
Gateway 进行不可绕过的第二次校验。

## Session

生产默认使用 `~/.local/state/smart_car/agent_sessions.sqlite3`，保存：

- 按 `session_id` 隔离的文字对话；
- 每次 `request_id` 对应的任务状态；
- Skill/Tool 结构化执行轨迹；
- 完成、取消或部分失败状态。

音频、图片和视频原文不写入 SQLite。Gateway 对同一 Session 串行执行，并对
已完成的 `request_id` 返回进程内缓存结果，防止客户端重试造成重复动作。

## 取消和安全

新任务或取消指令由 TaskManager 写入后台任务的 `cancel_token`。SkillRunner 在每个
模型轮次和 Tool 执行前检查取消；RobotToolClient 会取消正在执行的 Tool Action。
同步模型 HTTP 请求可能需要等当前调用返回，但取消后不会开始下一步动作。

安全链路固定为：

```text
模型决策 → Skill 权限 → ToolPolicy → Pydantic 参数 → Robot Gateway → Nav2/MCU
```

任意一层拒绝都会停止后续执行。
