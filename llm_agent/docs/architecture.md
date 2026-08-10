# Agent 架构

## 边界

`llm_agent` 是 ROS 网络中的统一 Agent 服务端，负责多模态理解、白名单工具、回复生成和可选语音合成。
它不采集麦克风、不读取摄像头设备、不播放扬声器，也不包含调试网页。

```text
树莓派 Agent Client ─┐
                    ├── /car/agent/run（RunAgent Action）
独立 Web Debug ─────┘
                              ↓
                     transport/ros
                              ↓
                         runtime
                              ↓
          agent / skills / models / tools / speech
```

所有外部调用方使用同一 Action。`AgentRuntime` 只接收纯 Python `RuntimeRequest`，不导入 ROS、HTTP、
浏览器或设备代码。

## 目录职责

| 目录 | 职责 |
| --- | --- |
| `runtime/` | 统一全模态契约、串行执行、取消、进度和响应转换 |
| `conversation/` | 按 `session_id` 隔离的短期多轮上下文及内存存储接口 |
| `transport/ros/` | `RunAgent` Action Server 以及 ROS/Runtime 类型转换 |
| `agent/` | LangGraph、共享状态、意图、安全、工具和回复节点 |
| `skills/` | 高层任务接口、注册表和由多个白名单 Tool 组成的任务计划 |
| `models/` | Provider 无关模型接口、能力声明、MiniCPM 和 MiniMax 适配 |
| `tools/` | 强类型工具协议、白名单和执行超时 |
| `adapters/audio/` | Piper 等独立语音合成适配器 |
| `prompts/` | 版本化系统、意图、回复和安全提示词 |
| `app/` | 配置加载和 ROS Agent Server 进程入口 |
| `tests/` | Runtime、Graph、Provider 和 ROS 转换单元测试 |

调试网页位于仓库顶层 `agent_debug_web/`，不属于 Agent 服务实现。

## 统一全模态请求

`RuntimeRequest.inputs` 是内容块数组，支持：

- `text`：自然语言或其他文本；
- `audio`：WAV 等音频；
- `image`：JPEG、PNG 等压缩图像；
- `video`：MP4 等视频；
- `json`：结构化上下文。

小型媒体通过 `data` 内联；接口同时预留 `uri` 和 `topic`。当前 Runtime 可以处理内联数据和 URI，实时
topic 引用必须先由客户端聚合成一次请求。默认内联总大小限制为 64 MiB。

`response_modalities` 声明期望输出。当前图始终返回文本；请求包含 `audio` 时再调用配置的 Speech
Provider。统一响应协议已支持文本、音频、图片和视频，实际生成能力由 Provider 能力声明决定。

## LangGraph

```text
START
  ↓
understand_intent
  ├── query/action + tool ─→ safety_check ─→ execute_tool ─┐
  ├── skill ─→ skill_safety_check ─→ execute_skill ────────┤
  └── 其他意图 ─────────────────────────────────────────────┤
                                                   ↓
                                          generate_response
                                                   ↓
                                          synthesize_speech
                                                   ↓
                                                  END
```

一轮通常包含一次意图识别和一次回复生成。动作请求、取消意图和无法识别请求使用确定性回答。工具调用还
必须同时满足请求允许工具、工具已注册和参数校验通过。

## Skill 与 Tool

Tool 是单次、强类型的原子能力；Skill 是完成一类复合任务的确定性编排。Skill 不直接访问 ROS、
Nav2 或硬件，而是先生成 `SkillPlan`，其中每一步仍是 `ToolCall`。计划中的全部 Tool 都通过注册表
白名单和 Pydantic 参数校验后，才能生成下发任务；任一步无效时整份计划都不会下发。

当前首个 Skill 是 `motion_sequence`，用于编排 2～8 个明确的直线和旋转步骤。单步运动继续直接调用
`move_relative` 或 `rotate_relative`，避免为简单动作增加额外层级。模型意图阶段只注入 Skill 名称和
简短说明，详细参数约束保留在提示词和代码模型中，避免未来 Skill 增多后把所有完整说明常驻上下文。

组合任务通过 `small_car.motion_sequence.v1` 下发。树莓派 `agent_client` 会再次逐步校验距离、角度、
字段和 schema，再按 Nav2 Action 的结果串行执行；任一步失败或取消都会清空剩余步骤。实时避障、轨迹
闭环和急停仍由 Nav2、Collision Monitor、底盘及 MCU 负责，而不是由 LLM 循环控制。

## 短期多轮上下文

`AgentRuntime` 在执行前根据 `session_id` 读取最近对话，在完成后写入本轮用户摘要和 Agent 文字回答。
默认使用 `conversation/InMemoryConversationStore`，按轮数、字符数、TTL 和最大会话数限制内存；服务
重启后自动清空。Web 默认使用 `web-debug`，树莓派在 Client 进程启动时生成独立 session，因此两端默认
不会混用历史。

历史只注入 `generate_response`，不会注入 `understand_intent`。这条边界保证“继续”“再来一次”等表达
不能从历史中继承距离或角度触发实车动作。文字请求保存原文；纯语音请求只保存意图模型的 `reason`
摘要，不保存 WAV、图片或视频二进制。`AgentRuntime.clear_conversation(session_id)` 可清空指定会话。

默认配置：

```yaml
runtime:
  conversation_enabled: true
  conversation_max_turns: 8
  conversation_max_context_chars: 12000
  conversation_ttl_seconds: 1800
  conversation_max_sessions: 128
```

## 并发和取消

ROS Action Server 可以同时接收多个 Goal，Runtime 使用锁串行访问模型，防止本地 GPU 被并发请求压垮。
排队请求可以在执行前取消；运行中的工具观察每个请求独立的取消令牌。已经发出的同步模型 HTTP 调用可能
要等当前调用返回后才能结束，但取消后不会继续后续业务步骤。
