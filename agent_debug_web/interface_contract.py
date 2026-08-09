"""读取已安装的统一 Agent Action 契约。"""

from __future__ import annotations

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory


def load_agent_action_name() -> str:
    package_share = Path(get_package_share_directory("small_car_interfaces"))
    contract_path = package_share / "config" / "interfaces.yaml"
    with contract_path.open(encoding="utf-8") as contract_file:
        contract = yaml.safe_load(contract_file)
    name = contract.get("actions", {}).get("agent_run", {}).get("name")
    if not isinstance(name, str) or not name.startswith("/"):
        raise RuntimeError("接口契约缺少统一 Agent Action")
    return name
