"""AgentRuntime 对外使用的稳定错误类型。

把 Runtime 抛出的异常分门别类，方便 transport 层按异常类型决定 ROS Action
Result 状态码（succeed / cancel / abort），也方便单元测试断言。
"""


class RuntimeStoppingError(RuntimeError):
    """Runtime 已进入停止状态，拒绝接收新请求。"""


class RequestCancelledError(RuntimeError):
    """请求在排队或执行过程中被调用方取消。"""


class UnsupportedMediaReferenceError(ValueError):
    """请求使用了当前部署无法解析的外部媒体引用（如未订阅的 ROS topic）。"""
