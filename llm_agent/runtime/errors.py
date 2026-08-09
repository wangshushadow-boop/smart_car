"""AgentRuntime 对外使用的稳定错误类型。"""


class RuntimeStoppingError(RuntimeError):
    """Runtime 已进入停止状态，拒绝接收新请求。"""


class RequestCancelledError(RuntimeError):
    """请求在排队或执行过程中被调用方取消。"""


class UnsupportedMediaReferenceError(ValueError):
    """请求使用了当前部署无法解析的外部媒体引用。"""
