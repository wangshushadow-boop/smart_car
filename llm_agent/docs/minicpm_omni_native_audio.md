# MiniCPM-o AWQ 语音能力限制

> 重要：当前 Agent 不调用 MiniCPM-o 的独立语音 WebSocket，也不注册 `speech.provider=minicpm`。
> 默认 `auto` 会为 MiniCPM 生成模型直接选择 Piper。不要把任意最终文本直接发送到
> `/v1/audio/speech/stream`。

当前方案在 RTX 3090 24GB 上运行 `MiniCPM-o-4_5-AWQ`，由 vLLM-Omni 的三个阶段完成
多模态理解、语音编码和 24 kHz 波形生成。

## 环境与模型

```text
MiniCPM 环境： `llm_agent/py_env/venvs/minicpm`
AWQ 模型：    /mnt/d/AI/models/MiniCPM-o-4_5-AWQ
服务地址：    http://127.0.0.1:8099
3090 配置：   llm_agent/config/minicpmo_4_5_awq_3090.yaml
```

脚本直接调用虚拟环境中的程序，正常启动不需要手工激活。需要手动执行 `python`、`pip`、
`vllm-omni` 或排查依赖时，可以复用同一环境：

```zsh
source llm_agent/py_env/venvs/minicpm/bin/activate
```

不要同时运行 8000 端口的普通 vLLM；RTX 3090 无法让两个服务同时驻留。

## 国内下载源优先

Python 包优先使用清华 PyPI：

```zsh
llm_agent/py_env/venvs/minicpm/bin/pip install \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple 包名
```

Hugging Face 模型优先设置国内端点并关闭 Xet：

```zsh
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
```

只有国内镜像不存在所需包或版本时，再临时回退官方源，不要把外部源设为默认值。

当前环境的 CUDA 头文件为 13.0。FlashInfer 本地编译要求编译组件保持同一版本，已验证的版本为：

```zsh
llm_agent/py_env/venvs/minicpm/bin/pip install \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  nvidia-cuda-nvcc==13.0.88 \
  nvidia-cuda-crt==13.0.88 \
  nvidia-cuda-cccl==13.0.85 \
  nvidia-nvvm==13.0.88
```

不要单独升级这些包，否则可能出现 CUDA 头文件不兼容或 PTX 版本不匹配。

## 启动与检查

进入 WSL 后运行：

```zsh
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_minicpm_omni.sh
```

首次启动需要编译 CUDA 内核，后续会复用缓存。看到 `Application startup complete` 表示三个阶段
都已完成加载。保持该终端运行，在另一个 WSL 终端检查：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8099/health
curl --noproxy '*' -fsS http://127.0.0.1:8099/v1/models
```

必须为本机请求绕过 HTTP 代理，否则代理可能返回 502，并不代表模型服务异常。

## 为什么禁用独立原生语音

MiniCPM-o Talker 的 Stage 1 不是普通的文本转语音服务。当前 vLLM-Omni 实现要求请求携带由 Stage 0
在同一次 Omni 流水线中产生的 `tts_token_ids` 和 `tts_hidden_states`。只发送 `input.text` 时，Stage 1
会因缺少条件张量而致命退出；这不是可以在 Agent 内捕获后再回退 Piper 的普通接口错误，因为整个
三阶段模型服务会先停止。

如果已经出现该错误，请停止发起请求的旧 Agent 或测试客户端，在模型终端按 `Ctrl+C`，然后重新运行：

```zsh
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_minicpm_omni.sh
```

启动后使用 `/health` 和 `/v1/models` 检查服务。语音输出请选择 Piper，或配置 MiniMax 的独立 T2A
接口。未来只有在上游提供稳定的独立 TTS API，或 Agent 能从同一次 completion 中可靠取得与最终文本
严格对应的音频时，才重新启用 MiniCPM 原生语音。

## 已验证结果

- AWQ 权重由 AutoAWQ Marlin 内核加载；
- Stage 0、Stage 1、Stage 2 均能在 RTX 3090 24GB 上驻留；
- 三阶段服务加载后 3090 显存基本满载，不能再并行启动其他 GPU 模型；
- 独立文本语音请求会缺少 Talker 条件张量，当前不属于受支持的 Agent 调用方式。
