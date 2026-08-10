"""全模态内容校验及模型输入转换。

模型 Provider 的 OpenAI 兼容接口统一接收 `data:` URL 或可访问的 URI，
本模块负责把 `RuntimeRequest` 拆解为四个 list，方便各节点复用。
"""

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
    # 不支持的实时 topic 引用：当前 Agent Server 没有拉流能力，直接拒掉。
    raise UnsupportedMediaReferenceError(
        f"当前 Agent Server 不能直接读取实时 topic 引用：{part.topic}"
    )


def model_inputs(request: RuntimeRequest) -> tuple[str, list[str], list[str], list[str]]:
    """提取文字、音频、图片和视频，供模型节点统一使用。

    返回值顺序固定：(text, audio_urls, image_urls, video_urls)。
    文本用 `\\n` 拼接并跳过空段，避免在 Prompt 里出现空行。
    """
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
