"""模型节点共享的全模态请求转换。"""

from __future__ import annotations

from llm_agent.runtime.contracts import RuntimeRequest
from llm_agent.runtime.media import model_inputs


def request_inputs(
    request: RuntimeRequest,
) -> tuple[str, list[str], list[str], list[str]]:
    """返回文字、音频、图片和视频输入，不暴露任何 ROS 类型。"""
    return model_inputs(request)
