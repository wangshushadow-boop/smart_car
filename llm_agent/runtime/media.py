"""全模态内容校验及模型输入转换。"""

from __future__ import annotations

import base64

from .contracts import ContentPart, ContentType, RuntimeRequest
from .errors import UnsupportedMediaReferenceError


def _as_data_url(part: ContentPart) -> str:
    """将内联二进制内容转换为模型接口通用的 data URL。"""
    if part.data:
        mime_type = part.mime_type or "application/octet-stream"
        encoded = base64.b64encode(part.data).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
    if part.uri:
        return part.uri
    raise UnsupportedMediaReferenceError(
        f"当前 Agent Server 不能直接读取实时 topic 引用：{part.topic}"
    )


def model_inputs(request: RuntimeRequest) -> tuple[str, list[str], list[str], list[str]]:
    """提取文字、音频、图片和视频，供模型节点统一使用。"""
    texts: list[str] = []
    audio: list[str] = []
    images: list[str] = []
    videos: list[str] = []
    for part in request.inputs:
        if part.type in {ContentType.TEXT, ContentType.JSON}:
            texts.append(part.text.strip())
        elif part.type == ContentType.AUDIO:
            audio.append(_as_data_url(part))
        elif part.type == ContentType.IMAGE:
            images.append(_as_data_url(part))
        elif part.type == ContentType.VIDEO:
            videos.append(_as_data_url(part))
    return "\n".join(filter(None, texts)), audio, images, videos
