"""Tool 白名单注册表，统一负责参数校验、超时控制和失败归一化。

关键约束：
- 只允许调用在白名单内的 Tool，所有参数走 `arguments_model` Pydantic 校验。
- 使用全局 `ThreadPoolExecutor` 串行化所有 Tool 调用，便于实现统一超时。
- 任何异常（参数、超时、运行错误）都会被归一化为 `ToolResult(success=False)`。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError

from pydantic import ValidationError

from .types import AgentTool, ToolCall, ToolContext, ToolResult


class ToolRegistry:
    """Tool 注册表与执行器。"""

    def __init__(self, default_timeout_seconds: float = 5.0) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("tool timeout must be positive")
        self._tools: dict[str, AgentTool] = {}
        self._default_timeout_seconds = default_timeout_seconds
        # 4 个并发 worker，足够支撑 motion_sequence 等组合任务；命名带前缀便于排查栈。
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="llm-agent-tool"
        )

    def register(self, tool: AgentTool) -> None:
        """注册 Tool；同名重复注册直接抛错。"""
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def contains(self, name: str) -> bool:
        """白名单查询；供 `safety_check`/`skill_safety_check` 节点拦截非法调用。"""
        return name in self._tools

    def names(self) -> list[str]:
        """按注册顺序返回工具名称，供 Prompt 和权限策略生成有效工具面。"""
        return list(self._tools)

    def definitions(self) -> list[AgentTool]:
        """返回只读语义的 Tool 定义快照，供 Skill 层生成原子能力视图。

        Tool 实例仍只保存在本 Registry 中；调用方只能获得当前快照，不能通过
        返回列表修改注册表。这样原子 Skill 无需复制 Tool 实现或重复注册执行器。
        """
        return list(self._tools.values())

    def catalog_prompt(self, names: list[str] | None = None) -> str:
        """为通用任务节点输出白名单工具及其参数 JSON Schema。"""
        lines: list[str] = []
        selected_names = self.names() if names is None else names
        for name in selected_names:
            tool = self._tools.get(name)
            if tool is None:
                raise ValueError(f"tool is not registered: {name}")
            schema = tool.arguments_model.model_json_schema()
            lines.append(f"- {name}: {tool.description}; 参数={schema}")
        return "\n".join(lines)

    def validate(self, call: ToolCall) -> str | None:
        """只校验白名单和参数，不执行 Tool。

        返回 `None` 表示校验通过；返回字符串即为错误描述。
        """
        tool = self._tools.get(call.name)
        if tool is None:
            return f"tool is not registered: {call.name}"
        try:
            tool.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return f"invalid tool arguments: {error}"
        return None

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """在线程池中执行 Tool，自动套用超时与取消令牌。"""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                name=call.name,
                success=False,
                error=f"tool is not registered: {call.name}",
            )
        # 进入执行前再检查一次取消，避免无意义的线程池排队。
        if context.cancelled.is_set():
            return ToolResult(name=call.name, success=False, error="request cancelled")
        try:
            arguments = tool.arguments_model.model_validate(call.arguments)
            timeout = float(
                getattr(tool, "timeout_seconds", self._default_timeout_seconds)
            )
            future = self._executor.submit(tool.execute, arguments, context)
            data = future.result(timeout=timeout)
            if not isinstance(data, dict):
                raise TypeError("tool result must be a dictionary")
            return ToolResult(name=call.name, success=True, data=data)
        except TimeoutError:
            # 超时：尝试取消 future（若 Tool 已在返回路径里就取消不了），但仍返回失败。
            future.cancel()
            return ToolResult(
                name=call.name,
                success=False,
                error=f"tool timed out after {timeout:g} seconds",
            )
        except ValidationError as error:
            return ToolResult(
                name=call.name,
                success=False,
                error=f"invalid tool arguments: {error}",
            )
        except Exception as error:
            return ToolResult(
                name=call.name,
                success=False,
                error=f"tool execution failed: {error}",
            )
