"""读取随 small_car_interfaces 安装的跨工程 ROS 接口契约。"""

from __future__ import annotations

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory


_REQUIRED_TOPICS = ("audio_input", "audio_output", "camera_image_compressed")


def load_topics() -> dict[str, str]:
    """返回经校验的共享 topic 名；缺失或格式错误时拒绝启动。"""
    package_share = Path(get_package_share_directory("small_car_interfaces"))
    contract_path = package_share / "config" / "interfaces.yaml"
    with contract_path.open(encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    topics = contract.get("topics", {}) if isinstance(contract, dict) else {}

    result: dict[str, str] = {}
    for key in _REQUIRED_TOPICS:
        name = topics.get(key, {}).get("name")
        if not isinstance(name, str) or not name.startswith("/"):
            raise RuntimeError(f"invalid ROS interface topic: {key}")
        result[key] = name
    return result
