"""统一 Agent Loop 的 Prompt 装配器。

只负责把请求、会话、Skill 摘要、有效 Tool Schema、任务规则和执行轨迹
拼成 Provider 无关的 ModelRequest；不调用模型，也不决定是否执行工具。
"""

from __future__ import annotations

from pathlib import Path

from llm_agent.sessions import ConversationTurn, format_conversation_history
from llm_agent.models.protocol import GenerationBackend, ModelRequest
from llm_agent.skills import RobotTask, SkillRegistry
from llm_agent.tools.registry import ToolRegistry


class PromptBuilder:
    """为 Agent Loop 生成包含最小必要上下文的模型请求。"""

    def __init__(
        self,
        model: GenerationBackend,
        skills: SkillRegistry,
        tools: ToolRegistry,
        prompt_directory: Path | None = None,
    ) -> None:
        self._model = model
        self._skills = skills
        self._tools = tools
        directory = prompt_directory or Path(__file__).resolve().parents[1] / "prompts"
        self._system_prompt = self._read_prompt(directory / "system.txt")
        self._safety_prompt = self._read_prompt(directory / "safety.txt")
        self._loop_prompt = self._read_prompt(directory / "agent_loop.txt")

    def build(
        self,
        *,
        user_text: str,
        history: list[ConversationTurn],
        allowed_tools: list[str],
        trace: list[dict],
        task: RobotTask | None,
        audio_urls: list[str],
        image_urls: list[str],
        video_urls: list[str],
    ) -> ModelRequest:
        """构造一轮模型决策请求，并按模型能力裁剪不支持的媒体。"""
        sections = [self._loop_prompt, self._safety_prompt]
        conversation = format_conversation_history(history)
        if conversation:
            sections.append(conversation)
        if user_text:
            sections.append(f"当前用户请求：{user_text}")
        if task is None:
            if allowed_tools:
                catalog = self._skills.catalog_prompt()
                if catalog:
                    sections.append(catalog)
        else:
            sections.append(
                "当前动态任务：\n"
                f"目标：{task.goal}\n"
                f"规则：{task.instructions}\n"
                f"最大步骤：{task.limits.max_steps}\n"
                f"超时：{task.limits.timeout_seconds:g}秒"
            )
        tool_catalog = self._tools.catalog_prompt(allowed_tools)
        sections.append("本轮允许工具：\n" + (tool_catalog or "无"))
        if trace:
            # Tool 结果可能较大，只保留最近记录的尾部文本，避免撑爆模型上下文。
            trace_text = str(trace[-8:])[-8000:]
            sections.append(f"最近执行轨迹：{trace_text}")
        return ModelRequest(
            system_prompt=self._system_prompt,
            user_prompt="\n\n".join(sections),
            audio_data_urls=audio_urls,
            image_data_urls=image_urls,
            video_data_urls=video_urls,
            max_tokens=self._model.capabilities.response_max_tokens,
            temperature=min(self._model.capabilities.response_temperature, 0.2),
        )

    @staticmethod
    def _read_prompt(path: Path) -> str:
        """读取版本化 Prompt；缺失或空内容时拒绝启动，避免无约束运行。"""
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RuntimeError(f"无法加载 Agent Prompt {path}: {error}") from error
        if not value:
            raise RuntimeError(f"Agent Prompt 为空：{path}")
        return value
