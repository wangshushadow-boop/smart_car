# 小车大模型与 Agent

该目录独立存放小车大模型、Agent、记忆系统和工具调用相关内容，避免与
STM32 固件及 ROS 2 底盘代码混在一起。

WSL 从零构建、整体备份和跨主机迁移步骤见：
[WSL 大模型环境构建与迁移手册](docs/wsl_deployment_and_migration.md)。

目前已部署的本地模型服务：

- WSL 发行版：`Ubuntu-24.04`
- WSL 用户：`llm_agent`
- 用户主目录：`/home/llm_agent`
- 通用 Agent 环境：`llm_agent/py_env/venvs/agent`
- MiniCPM 环境：`llm_agent/py_env/venvs/minicpm`
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
source llm_agent/py_env/venvs/agent/bin/activate
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

生成模型、媒体路由和语音输出策略在 `config/agent.yaml` 中配置：

```yaml
generation_model: minicpm       # minicpm | minimax

modalities:
  input:
    audio: {enabled: true, models: [qwen3_asr]}
    image: {enabled: true, models: [minicpm]}
    video: {enabled: true, models: [minicpm]}
  output:
    audio:
      enabled: true
      auto: "off"               # off | always | inbound
      mode: final
      models: [minimax, piper]
```

模型输入能力、路径、隔离 Python 环境、设备、服务地址和推理参数统一保存在
`config/models.yaml`。`agent.yaml` 只保留模型选择和 Agent 行为配置。

本地模型的 `deployment.command` 是不经过 Shell 的命令参数数组。例如：

```yaml
deployment:
  local: true
  command:
    - /path/to/python
    - -m
    - package.model_server
    - --port
    - 8100
  health_url: http://127.0.0.1:8100/health
```

启动器不包含 MiniCPM、Qwen 或 Piper 的名称判断；新增模型时只需要补充该配置。
如需设置单个服务的环境变量，可在 `deployment.environment` 中声明键值。健康检查
固定绕过系统代理，避免 WSL 的 `HTTP_PROXY` 导致本机服务被误报为超时。

音频输出按 `modalities.output.audio.models` 顺序尝试，前一个模型创建或合成失败时继续使用下一个。
`auto: "off"` 只处理调用方显式请求的音频输出，`always` 始终朗读，`inbound` 只回复语音输入。
当前 MiniCPM-o 服务没有安全的独立 TTS 接口，因此不放入语音链。可用 `CAR_GENERATION_MODEL` 和
逗号分隔的 `CAR_SPEECH_MODELS` 临时覆盖选择。MiniMax 云端能力需要：

```bash
export MINIMAX_API_KEY='请替换为云端密钥'
```

每个生成模型在 `models.yaml` 的对应条目中声明自己的生成参数：

```yaml
models:
  minimax:
    input: [text, image]
    response_max_tokens: 2048
    response_temperature: 0.2
    reasoning_split: true
```

`response_*` 用于统一 Agent Loop 的结构化决策。Runtime 会读取当前已选择
provider 的参数，切换 MiniCPM/MiniMax 时自动切换，不需要修改业务代码。`model`、`base_url`、
`timeout_seconds` 和 `max_retries` 也分别保留在该 provider 配置段；`reasoning_split` 仅由 MiniMax
适配器使用。

### 多模态输入自动路由

Agent 根据 `models.yaml` 的 `input` 属性选择输入路径：

- `minicpm` 支持音频，WAV 直接交给 MiniCPM；Qwen3-ASR Worker 不会启动。
- `minimax` 不支持音频，WAV 先由本地 Qwen3-ASR-0.6B 转写，再把文字交给 MiniMax。
- 主模型不支持图片或视频时，按 `modalities.input.image/video.models` 顺序调用理解模型；
  全部失败会明确返回错误，不会静默丢弃附件。

首次部署 ASR 环境和模型：

```bash
cd /mnt/d/work/smart_car
bash ./llm_agent/py_env/install_python_envs.sh
```

默认环境位于 `llm_agent/py_env/venvs/qwen3-asr`，模型位于
`/mnt/d/AI/models/Qwen3-ASR-0.6B`。两者与 MiniCPM 环境隔离；ASR 失败、超时或返回空文本时，
本轮请求降级为 unknown 且不会生成车辆运动任务。

当前 Agent 已按以下边界组织：

```text
llm_agent/
├── app/run_agent.py
├── gateway/gateway.py
├── runtime/
│   ├── agent_loop.py
│   ├── prompt_builder.py
│   └── contracts.py
├── sessions/store.py
├── models/
│   ├── protocol.py
│   ├── registry.py
│   └── providers/
├── tools/
│   ├── registry.py
│   ├── policy.py
│   ├── types.py
│   └── vehicle/
├── skills/
│   ├── loader.py
│   ├── registry.py
│   └── find_object/SKILL.yaml
├── transport/ros/
│   ├── run_agent_server.py
│   └── robot_tool_client.py
├── prompts/
├── config/
└── tests/
```

`__init__.py` 是 Python 包入口，不承担独立业务职责。`docs/`、`scripts/` 和
`py_env/` 仅保存文档、运维脚本与环境定义，不属于 Agent 运行模块。

不要把真实 API 密钥提交到 Git。后续启用鉴权时可使用本地 `.env` 文件，并把它加入 `.gitignore`。

Agent 对外只有 `/car/agent/run` 一个 ROS 2 Action，Goal、Feedback 和 Result 统一支持文本、音频、
图片、视频和 JSON 内容块。树莓派在设备侧完成 VAD 和相机关键帧聚合，再提交同一个 Action。

调试页面已拆分到仓库顶层独立模块 `agent_debug_web/`。它与树莓派完全一样，只是 `/car/agent/run`
的客户端，不导入 Runtime、模型、工具或 TTS。启动方法见
[独立 Web Debug](../agent_debug_web/README.md)。

当前 Agent Loop 支持闲聊、车辆状态查询、单步相对运动、组合运动 Skill、工具白名单校验和独立 TTS。
`motion_sequence` 可以把 2～8 个明确运动步骤编排为任务序列；树莓派再次校验后通过 Nav2 串行执行。
Agent Server 不直接发布速度或访问底盘，任意 ROS topic 发布也未开放。

动态机器人任务使用 `skills/<skill_name>/SKILL.yaml`，Agent 启动时自动扫描并注册。Skill 文件只声明
参数、目标模板、任务说明、允许工具和预算；所有动态 Skill 共用一个受约束 ReAct 执行节点，不需要
为新任务添加 Python 节点。新增或修改 Skill 后重启 Agent 生效，运行中不进行热加载。

已验证的语音对话启动、检查和排错步骤见[Agent 语音对话链路](docs/agent_ros_voice_loop.md)。
内部设计见[Agent 架构](docs/architecture.md)、[状态与事件](docs/agent_state.md)、
[模型 Provider](docs/model_providers.md)和[工具契约](docs/tool_contract.md)。

### 模型与 Agent 分离启动

本地模型按名称独立启动，模型进程不会由 Agent 创建。可以一次指定多个模型：

```bash
# MiniCPM + Piper
bash ./llm_agent/scripts/start_models.sh minicpm piper

# MiniMax + 媒体 fallback + Piper
bash ./llm_agent/scripts/start_models.sh qwen3_asr minicpm piper
```

另开终端启动 Agent：

```bash
bash ./llm_agent/scripts/start_agent.sh
```

模型终端退出只停止模型，Agent 终端退出只停止 Agent。模型部署定义位于
`config/models.yaml`，启动器不读取 `agent.yaml`。

查看完整参数和可启动模型：

```bash
bash ./llm_agent/scripts/start_models.sh --help
bash ./llm_agent/scripts/start_models.sh --list
```

不传参数时只显示帮助，不会启动模型。Agent 启动时会检查当前配置依赖的本地
模型；如有缺失会直接退出，并给出完整的 `start_models.sh <模型...>` 命令。
