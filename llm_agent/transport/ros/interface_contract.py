"""读取 small_car_interfaces 安装目录中的 Action 契约。"""

from __future__ import annotations

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory


def load_agent_action_name() -> str:
    """返回统一 Agent Action 名称，契约错误时拒绝启动。"""
    package_share = Path(get_package_share_directory("small_car_interfaces"))
    contract_path = package_share / "config" / "interfaces.yaml"
    with contract_path.open(encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    actions = contract.get("actions", {}) if isinstance(contract, dict) else {}
    name = actions.get("agent_run", {}).get("name")
    if not isinstance(name, str) or not name.startswith("/"):
        raise RuntimeError("统一 Agent Action 契约缺少 agent_run")
    return name
