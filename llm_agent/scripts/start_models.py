"""按 ``models.yaml`` Profile 统一启动本地模型服务。

本文件只负责模型进程的生命周期，不读取 ``agent.yaml``，也不会启动 Agent。
用户在命令行中明确给出一个或多个模型名；启动器依次创建子进程、等待健康
检查，并在任一服务退出或收到终止信号时关闭整组模型。
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import yaml


ROOT = Path(__file__).resolve().parents[2]


def command_for(name: str, deployment: dict) -> list[str]:
    """把一个模型的 deployment 配置转换为不经过 Shell 的命令参数数组。"""
    command = deployment.get("command")
    # MiniCPM 的 CUDA 环境变量和 vLLM 参数较多，继续复用专用启动脚本。
    if command == "minicpm":
        return ["bash", str(ROOT / "llm_agent/scripts/start_minicpm_omni.sh")]
    if command == "qwen3_asr":
        return [
            str(deployment["python"]),
            "-m",
            "llm_agent.models.qwen3_asr.server",
            "--model",
            str(deployment["model"]),
            "--device",
            str(deployment.get("device", "cuda:0")),
            "--host",
            str(deployment.get("host", "127.0.0.1")),
            "--port",
            str(deployment.get("port", 8100)),
        ]
    if command == "piper":
        return [
            str(deployment["python"]),
            "-m",
            "llm_agent.models.piper.server",
            "--model",
            str(deployment["model"]),
            "--config",
            str(deployment["config"]),
            "--host",
            str(deployment.get("host", "127.0.0.1")),
            "--port",
            str(deployment.get("port", 8101)),
        ]
    raise ValueError(f"unsupported deployment command for {name}: {command}")


def wait_ready(name: str, deployment: dict, process: subprocess.Popen) -> None:
    """轮询模型健康接口，直到服务就绪、进程退出或超过启动时限。"""
    health_url = str(deployment["health_url"])
    deadline = time.monotonic() + float(
        deployment.get("startup_timeout_seconds", 60)
    )
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"{name} exited during startup: {code}")
        try:
            with urlopen(health_url, timeout=2) as response:
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
            process = subprocess.Popen(command_for(name, deployment), cwd=ROOT)
            processes.append((name, process))
            wait_ready(name, deployment, process)
        if not processes:
            print(f"profile {args.profile} has no local models", flush=True)
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
