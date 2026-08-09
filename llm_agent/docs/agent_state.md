# Agent 请求与状态

## RuntimeRequest

所有 ROS Goal 都先转换为与 ROS 无关的 `RuntimeRequest`：

| 字段 | 含义 |
| --- | --- |
| `request_id` | 全局唯一请求 ID |
| `session_id` | 多轮会话关联 ID |
| `source` | `raspberry_pi`、`web_debug` 等调用方 |
| `inputs` | 文本、音频、图片、视频或 JSON 内容块 |
| `response_modalities` | 期望的文本、音频、图片或视频输出 |
| `allow_tools` | 是否允许白名单工具 |
| `stream_progress` | 是否发布 Action Feedback |
| `metadata` | 不承载大媒体的扩展字段 |

旧的 `SpeechFinished`、`TextReceived` 和字典兼容入口已经删除。

## AgentState

`AgentState` 只存在于一轮 LangGraph 执行期间：

| 字段 | 写入方 | 含义 |
| --- | --- | --- |
| `request_id` | Runtime | 当前请求 ID |
| `request` | Runtime | 统一全模态请求 |
| `cancel_token` | Runtime | 当前请求独立取消令牌 |
| `intent` | `understand_intent` | 结构化意图 |
| `tool_call` | `understand_intent` | 可选工具名和参数 |
| `tool_result` | `execute_tool` | 标准工具结果 |
| `answer` | `generate_response` | 最终文字 |
| `answer_wav` | `synthesize_speech` | 可选 WAV |
| `generation_backend` | 模型节点 | 实际模型 Provider |
| `speech_backend` | 语音节点 | 实际 Speech Provider |
| `error` | 任意节点 | 可诊断的部分失败 |

## RuntimeResponse

Runtime 把图状态转换为内容块数组。正常完成、失败和取消分别使用 `completed`、`failed`、`cancelled`。
TTS 失败时保留文字输出，并使用 `partial_failure` 说明部分失败。
