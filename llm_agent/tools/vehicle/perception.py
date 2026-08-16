"""受控云台与相机 Tool；生产环境全部通过 RobotToolClient 执行。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .motion import RobotToolExecutor


class CameraAngleArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    angle_deg: float


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _GatewayTool:
    timeout_seconds = 7.0

    def __init__(self, executor: RobotToolExecutor) -> None:
        self._executor = executor

    def _execute(self, arguments: dict, context, *, observation: bool = True) -> dict:
        return self._executor.execute(
            self.name,
            arguments,
            task_id=context.request_id,
            cancelled=context.cancelled,
            timeout_seconds=5.0,
            request_observation=observation,
        )


class SetCameraPanTool(_GatewayTool):
    name = "set_camera_pan"
    description = "设置相机水平云台角度，范围 -90 到 90 度"
    arguments_model = CameraAngleArguments

    def execute(self, arguments: CameraAngleArguments, context) -> dict:
        value = arguments.angle_deg
        if value < -90.0 or value > 90.0:
            raise ValueError("相机水平角度必须在 -90 到 90 度")
        return self._execute({"angle_deg": value}, context)


class SetCameraTiltTool(_GatewayTool):
    name = "set_camera_tilt"
    description = "设置相机俯仰角度，范围 -45 到 45 度"
    arguments_model = CameraAngleArguments

    def execute(self, arguments: CameraAngleArguments, context) -> dict:
        value = arguments.angle_deg
        if value < -45.0 or value > 45.0:
            raise ValueError("相机俯仰角度必须在 -45 到 45 度")
        return self._execute({"angle_deg": value}, context)


class CaptureCameraTool(_GatewayTool):
    name = "capture_camera"
    description = "获取小车前方相机的最新画面"
    arguments_model = NoArguments

    def execute(self, arguments: NoArguments, context) -> dict:
        del arguments
        return self._execute({}, context, observation=True)
