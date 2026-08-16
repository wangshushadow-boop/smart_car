"""扫描 ``skills/*/SKILL.yaml`` 并构造无代码的动态机器人 Skill。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from .registry import RobotTask, RobotTaskLimits, SkillRegistry

_SKILL_SCHEMA = "small_car.skill.v1"
_MAX_SKILL_BYTES = 64 * 1024
_PLACEHOLDER = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
_PYTHON_TYPES = {"string": str, "number": float, "integer": int, "boolean": bool}


class ArgumentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type_name: Literal["string", "number", "integer", "boolean"] = Field(
        alias="type"
    )
    required: bool = True
    min_length: int | None = Field(default=None, ge=0, le=4096)
    max_length: int | None = Field(default=None, ge=1, le=4096)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_constraints(self) -> "ArgumentDefinition":
        if self.type_name != "string" and (
            self.min_length is not None or self.max_length is not None
        ):
            raise ValueError("只有 string 参数支持长度限制")
        if self.type_name not in {"number", "integer"} and (
            self.minimum is not None or self.maximum is not None
        ):
            raise ValueError("只有 number/integer 参数支持数值限制")
        if self.min_length is not None and self.max_length is not None:
            if self.min_length > self.max_length:
                raise ValueError("min_length 不能大于 max_length")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("minimum 不能大于 maximum")
        return self


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[_SKILL_SCHEMA] = Field(alias="schema")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=256)
    arguments: dict[str, ArgumentDefinition] = Field(default_factory=dict)
    goal: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(min_length=1, max_length=4096)
    allowed_tools: list[str] = Field(min_length=1, max_length=32)
    limits: RobotTaskLimits = Field(default_factory=RobotTaskLimits)

    @model_validator(mode="after")
    def validate_manifest(self) -> "SkillManifest":
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("allowed_tools 不能包含重复名称")
        invalid_arguments = [
            name
            for name in self.arguments
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
        ]
        if invalid_arguments:
            raise ValueError(f"参数名不合法: {invalid_arguments}")
        placeholders = set(_PLACEHOLDER.findall(self.goal + self.instructions))
        unknown = placeholders.difference(self.arguments)
        if unknown:
            raise ValueError(f"模板引用了未声明参数: {sorted(unknown)}")
        return self


class DeclarativeRobotSkill:
    """由已校验 Manifest 驱动的动态目录 Skill。"""

    def __init__(self, manifest: SkillManifest) -> None:
        self.name = manifest.name
        self.description = manifest.description
        self.arguments_model = _create_arguments_model(manifest)
        self._manifest = manifest

    def create_task(self, arguments: BaseModel) -> RobotTask:
        values = arguments.model_dump()
        return RobotTask(
            name=self.name,
            goal=_render(self._manifest.goal, values),
            instructions=_render(self._manifest.instructions, values),
            allowed_tools=self._manifest.allowed_tools,
            limits=self._manifest.limits,
        )


def load_skill_directory(
    registry: SkillRegistry,
    tool_registry,
    root: Path | None = None,
) -> int:
    """加载直接子目录中的 Skill；任一错误均阻止启动，避免静默降级。"""
    skills_root = (root or Path(__file__).resolve().parent).resolve()
    loaded = 0
    for path in sorted(skills_root.glob("*/SKILL.yaml")):
        if path.resolve().parent.parent != skills_root:
            raise ValueError(f"Skill 目录不能通过链接逃逸扫描根目录: {path}")
        if path.stat().st_size > _MAX_SKILL_BYTES:
            raise ValueError(f"Skill 文件超过 64 KiB: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Skill 文件必须是 YAML 对象: {path}")
        manifest = SkillManifest.model_validate(raw)
        if path.parent.name != manifest.name:
            raise ValueError(
                f"Skill 目录名必须与 name 一致: {path.parent.name} != {manifest.name}"
            )
        missing = [
            name for name in manifest.allowed_tools if not tool_registry.contains(name)
        ]
        if missing:
            raise ValueError(f"Skill {manifest.name} 引用了未注册工具: {missing}")
        registry.register(DeclarativeRobotSkill(manifest))
        loaded += 1
    return loaded


def _create_arguments_model(manifest: SkillManifest) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for name, definition in manifest.arguments.items():
        python_type = _PYTHON_TYPES[definition.type_name]
        annotation = python_type if definition.required else python_type | None
        constraints: dict[str, Any] = {}
        if definition.type_name == "string":
            constraints.update(
                min_length=definition.min_length,
                max_length=definition.max_length,
            )
        elif definition.type_name in {"number", "integer"}:
            constraints.update(ge=definition.minimum, le=definition.maximum)
        fields[name] = (
            annotation,
            Field(... if definition.required else None, **constraints),
        )
    model_name = "".join(part.title() for part in manifest.name.split("_"))
    return create_model(
        f"{model_name}Arguments",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _render(template: str, values: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), template)
