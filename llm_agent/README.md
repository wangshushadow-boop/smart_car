# 小车大模型与 Agent

该目录独立存放小车大模型、Agent、记忆系统和工具调用相关内容，避免与
STM32 固件及 ROS 2 底盘代码混在一起。

WSL 从零构建、整体备份和跨主机迁移步骤见：
[WSL 大模型环境构建与迁移手册](docs/wsl_deployment_and_migration.md)。

目前已部署的本地模型服务：

- WSL 发行版：`Ubuntu-24.04`
- WSL 用户：`llm_agent`
- 用户主目录：`/home/llm_agent`
- Python 环境：`/opt/minicpm-service/venv`
- 模型目录：`/mnt/d/AI/models/MiniCPM-o-4_5-AWQ`
- API 地址：`http://127.0.0.1:8099/v1`
- API 模型名：`/mnt/d/AI/models/MiniCPM-o-4_5-AWQ`

## 1. 从 Windows 进入 WSL

在 Windows PowerShell 或 Windows Terminal 中执行：

```powershell
wsl -d Ubuntu-24.04 -u llm_agent
```

进入后，提示符会变成类似：

```text
llm_agent@主机名:/mnt/d/work/smart_car$
```

项目的 Windows 路径与 WSL 路径对应关系如下：

```text
D:\work\smart_car\llm_agent
/mnt/d/work/smart_car/llm_agent
```

进入脚本目录：

```bash
cd /mnt/d/work/smart_car/llm_agent
```

## 2. 进入模型 Python 环境

如果需要直接执行 Python、vLLM 或检查依赖，激活模型虚拟环境：

```bash
source /opt/minicpm-service/venv/bin/activate
```

激活后可检查环境：

```bash
which python
python --version
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name())"
vllm --version
```

退出 Python 虚拟环境：

```bash
deactivate
```

说明：运行本目录的脚本不需要手工激活虚拟环境，脚本会直接调用虚拟环境中的
`vllm` 和 `python`。

### 默认终端环境

WSL 用户 `llm_agent` 默认使用 Zsh，配置文件为 `/home/llm_agent/.zshrc`，
仓库中的配置模板为 `llm_agent/config/zshrc`。基础功能包括：

- Zsh 原生命令补全；
- 历史记录共享和方向键历史搜索；
- `zsh-autosuggestions` 命令自动建议；
- `zsh-syntax-highlighting` 命令语法高亮；
- `fzf` 模糊历史、文件及目录搜索。

如果修改了仓库模板，可在 WSL 中重新安装配置：

```bash
install -m 0644 /mnt/d/work/smart_car/llm_agent/config/zshrc ~/.zshrc
exec zsh
```

## 3. 启动模型

启动当前 MiniCPM-o Omni 服务：

```bash
./scripts/start_minicpm_omni.sh
```

首次启动通常需要约 1～2 分钟。启动脚本以前台方式运行，请保持这个 WSL
终端打开；按 `Ctrl+C` 可以停止模型。需要执行状态检查时，请另开一个
PowerShell/Windows Terminal 标签页，再次进入 WSL。

WSL 与普通 Linux 服务器不同：启动 WSL 的 Windows 客户端全部退出后，WSL
可能会清理孤立的 `nohup` 后台进程。因此脚本不使用不可靠的后台脱离方式。
模型日志直接输出在启动脚本所在的前台终端。

## 4. 检查状态

```bash
curl --noproxy '*' -fsS http://127.0.0.1:8099/health
curl --noproxy '*' -fsS http://127.0.0.1:8099/v1/models
```

查看显存：

```bash
watch -n 1 nvidia-smi
```

## 5. 停止模型

服务以前台方式运行，在启动模型的终端按 `Ctrl+C` 停止。

## 6. Agent 架构与调用参数

兼容 OpenAI API 的连接参数：

```text
Base URL: http://127.0.0.1:8099/v1
Model: /mnt/d/AI/models/MiniCPM-o-4_5-AWQ
API Key: EMPTY
```

Agent 通过 `127.0.0.1` 访问服务，但启动脚本当前使用 `0.0.0.0:8099` 监听且未启用 API 鉴权。
只应在受信任网络使用，并通过 Windows/WSL 防火墙限制 8099 端口，不要暴露到公网。

推理模型和语音后端在 `config/agent.yaml` 中独立选择：

```yaml
generation:
  provider: minicpm       # minicpm | minimax

speech:
  provider: auto          # auto | native | same_provider | piper | minimax
  preferred: same_provider
  fallback: piper
```

`auto` 优先使用推理 provider 已注册的独立语音能力，没有时直接使用 Piper。当前 MiniCPM-o 的
vLLM-Omni 服务没有安全的独立 TTS 接口，因此默认组合是 MiniCPM 推理 + Piper；MiniMax 仍可同时
提供云端文本和云端语音。显式指定 provider 时不会静默回退。可用 `CAR_GENERATION_PROVIDER`、
`CAR_SPEECH_PROVIDER` 临时覆盖选择。MiniMax 云端能力需要：

```bash
export MINIMAX_API_KEY='请替换为云端密钥'
```

当前 Agent 已按以下边界组织：

```text
llm_agent/
├── app/            # 配置和统一 ROS Action Server 进程入口
├── runtime/        # 与 ROS、Web、设备无关的全模态执行核心
├── transport/ros/  # RunAgent Action Server 和类型转换
├── agent/          # 状态、LangGraph 编排和业务节点
├── skills/         # 高层任务编排，只能组合白名单 Tool
├── models/         # MiniCPM-o 后端及输出解析
├── tools/          # 强类型白名单工具和统一执行注册表
├── adapters/audio/ # Piper TTS 等外部音频适配
├── prompts/        # 版本化系统、意图、回复和安全提示词
├── config/         # 不含密钥的配置模板
├── docs/           # 架构、接口、部署和运行文档
└── scripts/        # 模型和 Agent 运维脚本
```

不要把真实 API 密钥提交到 Git。后续启用鉴权时可使用本地 `.env` 文件，并把它加入 `.gitignore`。

Agent 对外只有 `/car/agent/run` 一个 ROS 2 Action，Goal、Feedback 和 Result 统一支持文本、音频、
图片、视频和 JSON 内容块。树莓派在设备侧完成 VAD 和相机关键帧聚合，再提交同一个 Action。

调试页面已拆分到仓库顶层独立模块 `agent_debug_web/`。它与树莓派完全一样，只是 `/car/agent/run`
的客户端，不导入 Runtime、LangGraph、模型、工具或 TTS。启动方法见
[独立 Web Debug](../agent_debug_web/README.md)。

当前图支持闲聊、车辆状态查询、单步相对运动、组合运动 Skill、工具白名单校验和独立 TTS。
`motion_sequence` 可以把 2～8 个明确运动步骤编排为任务序列；树莓派再次校验后通过 Nav2 串行执行。
Agent Server 不直接发布速度或访问底盘，任意 ROS topic 发布也未开放。

已验证的语音对话启动、检查和排错步骤见[Agent 语音对话链路](docs/agent_ros_voice_loop.md)。
内部设计见[Agent 架构](docs/architecture.md)、[统一请求与状态](docs/agent_state.md)、[模型 Provider](docs/model_providers.md)、
[状态与事件](docs/agent_state.md)和[工具契约](docs/tool_contract.md)。
