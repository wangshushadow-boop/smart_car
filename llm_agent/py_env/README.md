# Python 环境

`py_env` 是 `llm_agent` 所有 Python 环境的统一目录。每个环境都有同名的
`requirements-<name>.txt`，虚拟环境统一生成到 `venvs/<name>`。

| 环境 | 路径 | 依赖清单 | 用途 |
| --- | --- | --- | --- |
| Agent | `venvs/agent` | `requirements-agent.txt` | Agent、Web Debug、测试、Piper |
| MiniCPM | `venvs/minicpm` | `requirements-minicpm.txt` | vLLM-Omni 模型服务 |
| Qwen3-ASR | `venvs/qwen3-asr` | `requirements-qwen3-asr.txt` | 独立 ASR Worker |
| ROS 2 Trace | `venvs/ros2-trace` | `requirements-ros2-trace.txt` | trace 数据分析与可视化 |

在 WSL 的仓库根目录执行：

```bash
bash ./llm_agent/py_env/install_python_envs.sh
```

默认使用清华 PyPI 镜像、ModelScope 和 Hugging Face 国内镜像。可覆盖：

```bash
CAR_PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
HF_ENDPOINT=https://hf-mirror.com \
bash ./llm_agent/py_env/install_python_envs.sh
```

模型权重保存在 `/mnt/d/AI/models`，也可通过 `CAR_MODEL_DIR` 修改。虚拟环境和
模型权重都不提交 Git。

ROS 2 Kilted、`rclpy`、`ros2trace`、LTTng、Babeltrace 和 colcon 属于系统/ROS
依赖，不通过 pip 安装。先安装并 source `/opt/ros/kilted/setup.bash`，再使用
`llm_agent/scripts/setup_wsl_ros_env.sh` 构建项目 ROS 接口。
