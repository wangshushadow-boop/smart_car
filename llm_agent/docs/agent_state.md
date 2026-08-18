# Agent 请求与状态

## 稳定领域契约

外部 Adapter 只使用 `RuntimeRequest`、`RuntimeProgress` 和 `RuntimeResponse`。
ROS 消息转换集中在 `transport/ros/run_agent_server.py`，Runtime、Model、Skill 和
Tool 均不导入 ROS 类型。

`RuntimeRequest` 包含 `request_id`、`session_id`、来源、多模态内容、回复模态
和 `allow_tools`。`request_id` 用于幂等，`session_id` 用于上下文隔离和同会话
串行。

## 对话与后台任务状态

DialogueLoop 的状态只存在于一次短请求中；长 Skill 由 TaskManager 保存：

```text
用户输入与媒体引用
DialogueLoop：用户输入、当前任务快照、回答
TaskManager：task_id、status、取消令牌
SkillRunner：RobotTask、ToolBudget、execution_trace、最近 Observation
```

模型不能直接修改预算或执行状态，只能返回一个经过强类型解析的
`AgentDecision`。Tool 成功后才提交预算并把结果加入轨迹。

## 持久化 Session

SQLite 保存文字对话和请求事件，不保存媒体二进制。TaskManager 的最新任务
快照会进入下一轮 Prompt；AgentGateway 只串行化短对话轮次，不阻塞 SkillRunner。

后台任务状态统一为 `queued/running/completed/failed/cancelled/preempted`。
