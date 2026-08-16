# Agent 请求与状态

## 稳定领域契约

外部 Adapter 只使用 `RuntimeRequest`、`RuntimeProgress` 和 `RuntimeResponse`。
ROS 消息转换集中在 `transport/ros/run_agent_server.py`，Runtime、Model、Skill 和
Tool 均不导入 ROS 类型。

`RuntimeRequest` 包含 `request_id`、`session_id`、来源、多模态内容、回复模态
和 `allow_tools`。`request_id` 用于幂等，`session_id` 用于上下文隔离和同会话
串行。

## Agent Loop 状态

统一 Agent Loop 的状态只存在于一次请求中：

```text
用户输入与媒体引用
当前 RobotTask（可选）
ToolBudget
Skill/Tool execution_trace
最近 Robot Observation
取消令牌
最终 answer / audio / error
```

模型不能直接修改预算或执行状态，只能返回一个经过强类型解析的
`AgentDecision`。Tool 成功后才提交预算并把结果加入轨迹。

## 持久化 Session

SQLite 保存文字对话、Task Run 状态和结构化执行事件，不保存媒体二进制。
AgentGateway 保证同一 Session 不并发执行，并对已完成 request_id 返回缓存响应。

进度阶段包括 `queued`、`understanding`、`transcribing`、`agent_running`、
`tool_running`、`synthesizing` 和 `completed`。调用端应按阶段名称展示，不应
根据某个固定百分比推断动作已经成功。
