"""模型节点共享的全模态请求转换。

`understand_intent`、`generate_response` 等节点都需要把 `RuntimeRequest`
拆成 4 路媒体字段；为了不让每个节点都重复导入 runtime/media，这里提供一个
薄包装。同时这个间接层也用于在测试里替换 mock 输入。
"""

from __future__ import annotations

from llm_agent.runtime.contracts import RuntimeRequest
from llm_agent.runtime.media import model_inputs


def request_inputs(
    request: RuntimeRequest,
) -> tuple[str, list[str], list[str], list[str]]:
    """返回文字、音频、图片和视频输入，不暴露任何 ROS 类型。"""
    return model_inputs(request)
