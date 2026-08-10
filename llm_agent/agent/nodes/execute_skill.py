"""高层 Skill 的计划校验与声明式执行节点。

包含两个 LangGraph 节点：
- `create_skill_safety_node`：校验 Skill 名字 + 参数 + 每个 Tool 调用。
- `create_execute_skill_node`：在线程池里串行执行 Skill 内的 Tool。

要求每个被组合的 Tool 都返回 `MOTION_TASK_SCHEMA`，避免 Skill 引入非运动
任务；最终输出统一的 `MOTION_SEQUENCE_SCHEMA` 任务序列。
"""

from __future__ import annotations

from llm_agent.skills import SkillPlanResult, SkillRegistry
from llm_agent.tools.context import ToolContext
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.vehicle import MOTION_TASK_SCHEMA


MOTION_SEQUENCE_SCHEMA = "small_car.motion_sequence.v1"


def create_skill_safety_node(
    skill_registry: SkillRegistry, tool_registry: ToolRegistry
):
    """构造 Skill 校验节点：白名单 → Pydantic 参数 → 逐 Tool 二次校验。"""

    def validate_skill(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("skill_planning", 30, "正在生成并校验任务计划")
        if not state["request"].allow_tools:
            return {"error": "本轮请求禁止调用工具"}
        call = state.get("skill_call")
        if call is None:
            return {"error": "模型没有提供 Skill 调用"}
        if not skill_registry.contains(call.name):
            return {"error": f"Skill 未在白名单中：{call.name}"}
        try:
            plan = skill_registry.plan(call)
        except ValueError as error:
            return {"error": str(error)}
        # 计划展开后还要校验每个 Tool 调用，避免 Skill 把非法 Tool 包装进来。
        for tool_call in plan.tool_calls:
            error = tool_registry.validate(tool_call)
            if error:
                return {"error": f"Skill 计划包含无效工具调用：{error}"}
        return {"skill_plan": plan}

    return validate_skill


def create_execute_skill_node(tool_registry: ToolRegistry):
    """构造 Skill 执行节点：串行执行 Tool，任一失败立即中止整组任务。"""

    def execute_skill(state: dict) -> dict:
        progress = state.get("progress_callback")
        if progress:
            progress("skill_running", 45, "正在生成受约束任务序列")
        plan = state["skill_plan"]
        context = ToolContext(
            request_id=state["request_id"],
            cancelled=state["cancel_token"],
            services={},
        )
        results = []
        commands = []
        for call in plan.tool_calls:
            result = tool_registry.execute(call, context)
            results.append(result)
            if not result.success:
                # 任一 Tool 失败立即终止，不继续后续步骤，避免组合任务半途而废。
                return {
                    "skill_result": SkillPlanResult(
                        name=plan.name,
                        success=False,
                        tool_results=results,
                        error=result.error,
                    ),
                    "error": f"Skill 工具执行失败：{result.error}",
                }
            if result.data.get("schema") != MOTION_TASK_SCHEMA:
                # Skill 当前仅支持运动类 Tool 的组合；其他类型直接拒掉。
                return {
                    "skill_result": SkillPlanResult(
                        name=plan.name,
                        success=False,
                        tool_results=results,
                        error="Skill 当前只允许组合运动 Tool",
                    ),
                    "error": "Skill 产生了不支持的任务类型",
                }
            commands.append(result.data)
        return {
            "skill_result": SkillPlanResult(
                name=plan.name, success=True, tool_results=results
            ),
            "command": {
                "schema": MOTION_SEQUENCE_SCHEMA,
                "skill": plan.name,
                "steps": commands,
            },
        }

    return execute_skill
