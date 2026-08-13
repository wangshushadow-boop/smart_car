"""ROS 2 tracing 的可选适配层。

本模块为 Agent 的关键 Action 回调补充与 rclcpp 回调一致的 trace 事件，便于
使用 ``ros2 trace`` 观察回调耗时。tracetools 属于 ROS 系统依赖，不安装在
Agent 虚拟环境中，因此这里通过 ``ctypes`` 动态加载 ROS 提供的共享库。

Tracing 是可选诊断能力：共享库不存在、ROS 未启用 tracing 或符号不完整时，
``ros_trace_scope`` 会安全退化为空上下文，绝不能阻止 Agent 启动或处理请求。
"""

from __future__ import annotations

import ctypes
import ctypes.util
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator


@lru_cache(maxsize=1)
def _trace_library():
    """加载 ROS tracetools 共享库；不可用时返回 ``None``。

    ``find_library`` 在已配置 ldconfig 的 Linux 上通常可以直接找到库。WSL 的
    ROS 环境有时只通过安装目录提供共享库，因此再检查 Kilted 的标准路径。
    捕获全部加载错误是有意设计：tracing 不能成为 Agent 的强制运行依赖。
    """
    candidates = [
        ctypes.util.find_library("tracetools"),
        "/opt/ros/kilted/lib/libtracetools.so",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).is_absolute() and not Path(candidate).is_file():
            continue
        try:
            library = ctypes.CDLL(candidate)
            # 只有三个必需符号全部存在时才启用，防止 ROS 版本不匹配。
            library.ros_trace_rclcpp_callback_register
            library.ros_trace_callback_start
            library.ros_trace_callback_end
            return library
        except (AttributeError, OSError):
            continue
    return None


def _callback_pointer(callback) -> ctypes.c_void_p:
    """为普通函数或绑定方法生成进程内稳定的非空标识。

    每次读取 ``instance.method`` 都会创建新的临时方法对象，直接使用它的
    ``id`` 会变化。因此绑定方法使用实例和底层函数的身份组合；普通函数直接
    使用自身身份。该值只用于同一进程内关联 trace 事件，不会解引用。
    """
    instance = getattr(callback, "__self__", None)
    function = getattr(callback, "__func__", callback)
    identity = id(function)
    if instance is not None:
        identity ^= id(instance)
    # c_void_p(NULL) 会被 tracing 误认为无回调；理论上异或可能为零，因此兜底 1。
    return ctypes.c_void_p(identity or 1)


@contextmanager
def ros_trace_scope(callback, name: str) -> Iterator[None]:
    """在代码块前后发出平衡的 ROS callback trace 事件。

    参数：
        callback: 当前回调函数，用于生成稳定身份标识。
        name: trace 中显示的人类可读回调名称。

    即使代码块抛出异常，也会在 ``finally`` 中发送 callback_end；如果 tracing
    不可用则直接执行代码块，不改变原有控制流。
    """
    library = _trace_library()
    if library is None:
        yield
        return

    pointer = _callback_pointer(callback)
    # Fake 测试库接收 str；ctypes 动态库需要 char*。仅对真实 CDLL 编码。
    trace_name = name.encode("utf-8") if isinstance(library, ctypes.CDLL) else name
    try:
        library.ros_trace_rclcpp_callback_register(pointer, trace_name)
        library.ros_trace_callback_start(pointer, False)
    except Exception:
        # 动态库 ABI 与当前 ROS 不一致时也必须安全降级，不能影响业务回调。
        yield
        return
    try:
        yield
    finally:
        library.ros_trace_callback_end(pointer)
