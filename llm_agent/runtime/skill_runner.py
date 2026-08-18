"""后台执行单步、固定计划和动态 ReAct Skill。"""

from __future__ import annotations

import base64

from llm_agent.models.protocol import sanitize_spoken_answer
from llm_agent.skills import SkillRegistry
from llm_agent.tools.policy import ToolBudget, ToolPolicy
from llm_agent.tools.registry import ToolRegistry
from llm_agent.tools.types import ToolContext
from llm_agent.tools.vehicle import MOTION_TASK_SCHEMA

from .prompt_builder import PromptBuilder
from .reactor import Reactor
from .task_manager import TaskRecord

_MOTION_SEQUENCE_SCHEMA = "small_car.motion_sequence.v1"


class SkillRunner:
    """只负责完成一个后台 Skill，不管理会话、线程或任务优先级。"""

    def __init__(
        self,
        *,
        reactor: Reactor,
        tools: ToolRegistry,
        skills: SkillRegistry,
        policy: ToolPolicy,
        prompt_builder: PromptBuilder,
        robot_tool_executor=None,
        max_model_turns: int = 20,
    ) -> None:
        self._reactor = reactor
        self._tools = tools
        self._skills = skills
        self._policy = policy
        self._prompt_builder = prompt_builder
        self._robot_tool_executor = robot_tool_executor
        self._max_model_turns = max_model_turns

    def run(self, record: TaskRecord) -> dict:
        """按 Skill 类型选择确定性执行或有界 ReAct。"""
        call = record.submission.skill_call
        if self._skills.is_reactive(call.name):
            return self._run_reactive(record)
        return self._run_planned(record)

    def stop(self) -> None:
        """释放唯一 ToolRegistry 持有的执行线程池。"""
        self._tools.close()

    def _run_planned(self, record: TaskRecord) -> dict:
        """单步和固定计划不调用多轮模型，工具全部成功即完成。"""
        trace: list[dict] = []
        commands: list[dict] = []
        budget = ToolBudget.start()
        context = self._context(record)
        error = self._execute_plan(
            record.submission.skill_call,
            context,
            trace,
            budget,
            commands,
        )
        if error:
            return self._failure(error, trace)
        state = {
            "answer": f"{record.submission.skill_call.name} 已执行完成。",
            "generation_backend": self._reactor.provider_name,
            "execution_trace": trace,
            "skill_snapshot": self._skills.snapshot_id(),
        }
        self._attach_commands(state, commands, record.submission.skill_call.name)
        return state

    def _run_reactive(self, record: TaskRecord) -> dict:
        """动态 Skill 采用观察—决策—动作循环，并在每一步响应抢占。"""
        call = record.submission.skill_call
        try:
            robot_task = self._skills.create_task(call)
        except ValueError as error:
            return self._failure(str(error))

        trace: list[dict] = [{"kind": "skill", "name": call.name, "goal": robot_task.goal}]
        commands: list[dict] = []
        images = list(record.submission.image_urls)
        budget = ToolBudget.start()
        context = self._context(record)
        last_provider = ""

        for turn in range(1, self._max_model_turns + 1):
            if record.cancelled.is_set():
                return self._failure("任务已取消或被抢占", trace)
            allowed = self._policy.allowed_tools(robot_task)
            try:
                decision, last_provider = self._reactor.decide(
                    request_id=record.task_id,
                    stage="skill_runner",
                    turn=turn,
                    prompt=self._prompt_builder.build_skill(
                        task=robot_task,
                        trace=trace,
                        allowed_skills=allowed,
                        image_urls=images,
                    ),
                )
            except Exception as error:
                return self._failure(f"Skill 决策解析失败：{error}", trace)

            if decision.type == "final":
                answer = sanitize_spoken_answer(decision.answer)
                state = {
                    "answer": answer or "任务已经结束。",
                    "generation_backend": last_provider,
                    "execution_trace": trace,
                    "skill_snapshot": self._skills.snapshot_id(),
                }
                if decision.status == "failed":
                    state["error"] = decision.reason or "模型报告任务失败"
                self._attach_commands(state, commands, robot_task.name)
                return state

            if decision.type != "skill_call":
                return self._failure("后台 Skill 不允许控制其他任务", trace)
            if not self._skills.is_atomic(decision.skill_name or ""):
                return self._failure("动态任务只能调用获授权的原子 Skill", trace)

            atomic_call = self._skill_call(decision.skill_name or "", decision.arguments)
            trace.append(
                {
                    "kind": "skill",
                    "name": atomic_call.name,
                    "mode": "atomic",
                    "parent": robot_task.name,
                }
            )
            error = self._execute_plan(
                atomic_call,
                context,
                trace,
                budget,
                commands,
                robot_task,
            )
            if error:
                return self._failure(error, trace)
            self._collect_observations(record.task_id, images)
        return self._failure("Skill 达到最大模型决策轮数", trace)

    def _execute_plan(
        self,
        call,
        context: ToolContext,
        trace: list[dict],
        budget: ToolBudget,
        commands: list[dict],
        robot_task=None,
    ) -> str | None:
        """展开计划并逐个执行 Tool；每步都经过统一策略校验。"""
        try:
            plan = self._skills.plan(call)
        except ValueError as error:
            return str(error)
        for tool_call in plan.tool_calls:
            if context.cancelled.is_set():
                return "任务已取消或被抢占"
            policy_error = self._policy.validate(tool_call, budget, robot_task)
            if policy_error:
                return f"Skill 工具策略拒绝：{policy_error}"
            result = self._tools.execute(tool_call, context)
            trace.append(
                {
                    "kind": "tool",
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                }
            )
            if not result.success:
                return result.error or "Skill 工具执行失败"
            self._policy.consume(tool_call, budget)
            if result.data.get("schema") == MOTION_TASK_SCHEMA:
                commands.append(result.data)
        return None

    def _collect_observations(self, task_id: str, image_urls: list[str]) -> None:
        """把 Robot Gateway 的最新 JPEG 追加为下一轮观察。"""
        if self._robot_tool_executor is None:
            return
        for data in self._robot_tool_executor.take_observations(task_id):
            encoded = base64.b64encode(data).decode("ascii")
            image_urls.append(f"data:image/jpeg;base64,{encoded}")
        if len(image_urls) > 4:
            del image_urls[:-4]

    @staticmethod
    def _context(record: TaskRecord) -> ToolContext:
        return ToolContext(
            request_id=record.task_id,
            cancelled=record.cancelled,
            services={},
        )

    @staticmethod
    def _skill_call(name: str, arguments: dict):
        from llm_agent.skills import SkillCall

        return SkillCall(name=name, arguments=arguments)

    @staticmethod
    def _attach_commands(state: dict, commands: list[dict], skill_name: str) -> None:
        if not commands:
            return
        state["command"] = (
            commands[0]
            if len(commands) == 1
            else {
                "schema": _MOTION_SEQUENCE_SCHEMA,
                "skill": skill_name,
                "steps": commands,
            }
        )

    @staticmethod
    def _failure(message: str, trace: list[dict] | None = None) -> dict:
        return {
            "answer": "任务未能完成，车辆已经停止继续执行。",
            "error": message,
            "execution_trace": trace or [],
        }
