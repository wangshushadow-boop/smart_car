"""按 ``models.yaml`` 统一启动本地模型服务。

本文件只负责模型进程的生命周期，不读取 ``agent.yaml``，也不会启动 Agent。
用户在命令行中明确给出一个或多个模型名；启动器依次创建子进程、等待健康
检查，并在任一服务退出或收到终止信号时关闭整组模型。
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import yaml


ROOT = Path(__file__).resolve().parents[2]


def command_for(name: str, deployment: dict) -> list[str]:
    """读取通用命令数组；启动器不识别任何具体模型或推理框架。"""
    command = deployment.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError(f"{name} deployment.command 必须是非空参数数组")
    if not all(isinstance(argument, (str, int, float)) for argument in command):
        raise ValueError(f"{name} deployment.command 只能包含字符串或数字")
    return [str(argument) for argument in command]


def process_environment(name: str, deployment: dict) -> dict[str, str]:
    """把可选环境变量合并到当前环境，不经过 Shell 展开。"""
    configured = deployment.get("environment", {})
    if not isinstance(configured, dict):
        raise ValueError(f"{name} deployment.environment 必须是对象")
    environment = os.environ.copy()
    environment.update({str(key): str(value) for key, value in configured.items()})
    return environment


def wait_ready(name: str, deployment: dict, process: subprocess.Popen) -> None:
    """轮询模型健康接口，直到服务就绪、进程退出或超过启动时限。"""
    health_url = str(deployment["health_url"])
    # 本地健康检查不得经过 HTTP_PROXY；否则 WSL 中即使服务已经监听，
    # urllib 仍可能把 127.0.0.1 请求发给代理并最终误报超时。
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + float(
        deployment.get("startup_timeout_seconds", 60)
    )
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"{name} exited during startup: {code}")
        try:
            with opener.open(health_url, timeout=2) as response:
                if response.status == 200:
                    print(f"model ready: {name} ({health_url})", flush=True)
                    return
        except Exception:
            # 模型加载期间连接失败属于正常状态；按一秒间隔继续探测。
            time.sleep(1)
    raise TimeoutError(f"{name} health check timed out: {health_url}")


def main() -> int:
    """解析命令行并以前台方式管理一个模型 Profile。"""
    parser = argparse.ArgumentParser(
        description="按名称启动 models.yaml 中定义的一个或多个本地模型（不启动 Agent）。",
        epilog=(
            "可以一次输入多个模型名，启动器会依次启动并等待全部健康。\n"
            "示例：\n"
            "  start_models.sh qwen3_asr piper # 同时启动 ASR 和语音合成\n"
            "  start_models.sh minicpm piper   # 同时启动 MiniCPM 和 Piper\n"
            "  start_models.sh piper           # 仅启动 Piper\n"
            "按 Ctrl+C 会统一停止本次启动的全部模型服务。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
    parser.add_argument(
        "models",
        nargs="*",
        metavar="MODEL",
        help="要启动的本地模型名，可一次指定多个",
    )
    parser.add_argument(
        "--config",
        default=str(ROOT / "llm_agent/config/models.yaml"),
        help="模型配置文件路径（默认：llm_agent/config/models.yaml）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出全部可启动的本地模型，然后退出",
    )
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    configured_models = config.get("models", {})
    if args.list:
        local_models = {
            name: model
            for name, model in configured_models.items()
            if model.get("deployment", {}).get("local", False)
        }
        if not local_models:
            print("没有配置可启动的本地模型")
            return 0
        print("可启动的本地模型：")
        for name, model in sorted(local_models.items()):
            roles = ", ".join(model.get("roles", []))
            print(f"  {name}: {roles}")
        return 0
    if not args.models:
        parser.print_help()
        return 0
    names = list(dict.fromkeys(args.models))
    available = sorted(
        name
        for name, model in configured_models.items()
        if model.get("deployment", {}).get("local", False)
    )
    invalid = [name for name in names if name not in available]
    if invalid:
        raise SystemExit(
            f"模型不可启动或不存在：{', '.join(invalid)}；"
            f"可用模型：{', '.join(available)}"
        )

    processes: list[tuple[str, subprocess.Popen]] = []

    def stop_all(*_args) -> None:
        """先请求全部服务退出，再强制清理十秒内未结束的进程。"""
        # 逆序停止，优先关闭后启动的轻量依赖服务。
        for _name, process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for _name, process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def interrupt(*_args) -> None:
        """把 SIGINT/SIGTERM 汇合到统一的 finally 清理路径。"""
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        for name in names:
            model = configured_models[name]
            deployment = model.get("deployment", {})
            # 云端 Provider 只用于 Agent 调用，不属于本地进程组。
            if not deployment.get("local", False):
                continue
            print(f"starting model: {name}", flush=True)
            process = subprocess.Popen(
                command_for(name, deployment),
                cwd=ROOT,
                env=process_environment(name, deployment),
            )
            processes.append((name, process))
            wait_ready(name, deployment, process)
        if not processes:
            print("没有启动任何本地模型", flush=True)
            return 0
        print(f"models ready: {', '.join(names)}", flush=True)
        while True:
            # 前台驻留并监控所有子进程，避免某个服务静默退出。
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"model service exited: {name} ({code})")
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
