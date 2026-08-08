# Agent 事件与状态

## 输入事件

所有外部输入必须先转换为 `AgentEvent`，LangGraph 不直接接收 ROS 消息。

| 事件 | 主要字段 | 用途 |
| --- | --- | --- |
| `SpeechFinished` | `speech_wav`、`perception` | 一段用户语音结束后触发推理 |
| `TextReceived` | `text`、`perception` | 测试或未来文本入口 |
| `BargeIn` | 公共事件字段 | 用户打断当前交互 |
| `TaskCancelled` | `reason` | 取消当前任务 |
| `RobotFault` | `code`、`message` | 机器人故障事件预留 |

公共字段：

- `event`：稳定事件名称；
- `request_id`：每轮唯一 ID，用于关联图、工具和日志；
- `created_at`：UTC 事件创建时间。

迁移期间 `event_from_legacy()` 仍接受旧字典格式，但新输入代码应直接构造事件类型。

## LangGraph 状态

`AgentState` 是一轮执行中的共享状态，不是长期记忆：

| 字段 | 写入方 | 含义 |
| --- | --- | --- |
| `request_id` | Runtime | 当前请求 ID |
| `event` | Runtime | 标准输入事件 |
| `intent` | `understand_intent` | 结构化意图判断 |
| `tool_call` | `understand_intent` | 可选工具名和参数 |
| `tool_result` | `execute_tool` | 标准化工具结果 |
| `answer` | `generate_response` | 最终用户可见文本 |
| `answer_wav` | `synthesize_speech` | Piper 生成的 WAV |
| `error` | 任意失败节点 | 可诊断错误，不等同于任务成功 |

意图枚举：

- `chat`：普通问答，不调用工具；
- `query`：查询真实机器人状态，必须使用白名单只读工具；
- `action`：动作请求，当前确定性拒绝；
- `cancel`：停止或取消请求；
- `unknown`：无法解析或模型输出格式错误。

## 错误和降级

- 意图 JSON 无效：转为 `unknown`，不尝试工具调用；
- 模型回复失败：返回固定的暂时不可用文本；
- 工具未注册：安全检查拒绝，工具不会执行；
- 工具参数无效或超时：产生失败的 `ToolResult`；
- TTS 失败：保留文本回答，并把原因写入 `error`；
- Runtime 进入停止状态：拒绝接收新轮次。

`error` 只用于诊断和生成诚实回复，不能由模型将失败解释成执行成功。
