# Agent 架构

## 目标与边界

`llm_agent` 是小车的非实时认知与交互层，负责理解用户请求、选择白名单工具并生成回复。它不承担
电机闭环、避障、急停或底盘实时控制。即使 Agent 给出错误结果，ROS 与 MCU 侧也必须独立保证安全。

当前完成阶段 1～5，形成以下依赖方向：

```text
ROS 音频/图像
    ↓
input：VAD、回声抑制、感知聚合
    ↓ SpeechFinished / TextReceived
app：进程装配与生命周期
    ↓
agent：LangGraph 决策编排
    ├──→ models：本地/云端生成、原生语音、能力与 provider 注册
    ├──→ tools：白名单、参数校验、超时与结果
    └──→ adapters/audio：Piper TTS
    ↓
ROS 音频输出
```

依赖约束：

- `agent` 不导入 ROS 消息类型，也不直接发布 topic；
- `models` 只处理模型请求和文本响应，不执行 TTS；
- `tools` 只执行注册表中显式注册的能力；
- 提示词不能替代工具参数校验和程序安全检查；
- 原始 WAV 和图像仅用于当前轮推理，不作为长期记忆保存。

## 目录职责

| 目录 | 当前职责 |
| --- | --- |
| `app/` | 创建运行时和 ROS 输入节点，处理启动与退出 |
| `agent/` | 标准事件、共享状态、LangGraph、节点和提示词加载 |
| `models/` | 统一生成/语音接口、能力声明、provider 注册、MiniCPM 与 MiniMax 实现 |
| `tools/` | 工具协议、执行上下文、注册表和车辆只读工具 |
| `adapters/audio/` | TTS 协议和 Piper 实现 |
| `input/` | ROS 音视频订阅、VAD、回声抑制、语音聚合与播放发布 |
| `prompts/` | 系统、意图、回复和安全提示词 |
| `tests/` | 图路由、事件、工具、解析和音频单元测试 |

`input/ros_perception.py` 暂时仍同时承担输入聚合和音频输出，以避免一次性破坏已验证的语音闭环。
音频与 ROS 适配的进一步拆分安排在后续阶段。

## 当前 LangGraph

```text
START
  ↓
understand_intent
  ├── chat/action/cancel/unknown ─────────────┐
  └── query + tool_call                       │
             ↓                                │
        safety_check                          │
          ├── 拒绝 ───────────────────────────┤
          └── 允许                            │
               ↓                              │
          execute_tool                        │
               └──────────────────────────────┤
                                              ↓
                                      generate_response
                                              ↓
                                      synthesize_speech
                                              ↓
                                             END
```

图每轮最多执行一个工具，因此当前不存在无限工具循环。动作意图使用确定性回复拒绝，不会进入工具层。

## 模型与语音

推理和语音是两个独立选择：

```text
GenerationBackend.complete(ModelRequest) -> ModelResponse
SpeechBackend.synthesize(SpeechRequest) -> SpeechResponse
```

MiniCPM-o 支持本机图像、音频、文本输入和 Omni 原生语音；MiniMax 文本走云端 OpenAI 兼容接口，
MiniMax 语音走独立 T2A API；Piper 是模型无关的本地后端。`auto` 可组合原生语音与 Piper 回退。
最终文本先经过清洗，再发送给语音 provider，因此播报内容与用户可见答案一致。语音失败只影响播报，
不会丢失文本回复。详细配置与能力矩阵见[模型 Provider](model_providers.md)。

## 当前能力和后续阶段

当前能力：

- 多模态语音与当前画面输入；
- `chat`、`query`、`action`、`cancel`、`unknown` 意图；
- 工具白名单、Pydantic 参数校验、执行超时和统一错误；
- 只读 `get_robot_status` 工具；
- 独立 TTS、回声抑制和用户打断。

尚未实现：

- 阶段 6：ROS `VehicleGateway` 和真实车辆状态；
- 阶段 7：完整动作安全策略和高优先级停车通道；
- 阶段 8：受控导航或运动工具；
- 阶段 9：对话记忆和任务状态；
- 阶段 10：进一步拆分 ROS 与音频输入模块。
