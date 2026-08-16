# 模型 Provider

## 三类独立接口

Agent 将理解/回复、语音识别和语音合成分成三个接口：

```text
GenerationBackend 处理文本、图像、音频输入并返回最终文本
AsrBackend        在生成模型不支持音频时把语音转成文本
SpeechBackend     接收最终文本并返回标准 WAV
```

两者可以来自不同 provider。例如使用本地 MiniCPM 理解摄像头与麦克风，同时使用 MiniMax 云端语音；
也可以使用 MiniMax 文本模型和本地 Piper。Agent Loop 和 ROS 输出不依赖具体厂商。

## 当前 Provider

| Provider | 文本生成 | 图像输入 | 音频输入 | 语音输出 |
| --- | ---: | ---: | ---: | ---: |
| `minicpm` | 是 | 是 | 是 | 否（当前服务无安全的独立 TTS） |
| `minimax` | 是 | 是（M3） | 否 | 云端 T2A WAV |
| `piper` | 不适用 | 不适用 | 不适用 | 本地 WAV |

MiniMax-M3 的 OpenAI/Anthropic 兼容接口支持文本和图片；适配器会把 Runtime 的图片 data URL 转成
对应协议的图片内容块。M3 不直接接收音频，音频会按媒体路由交给 Qwen3-ASR；视频可回退到
MiniCPM。MiniCPM 原生接收文本、图片、音频和视频。无法处理的附件会明确报错，不再过滤丢弃。

## 配置

模型选择位于 `llm_agent/config/agent.yaml`，模型参数统一位于
`llm_agent/config/models.yaml`：

```yaml
generation_model: minicpm

modalities:
  input:
    audio: {enabled: true, models: [qwen3_asr]}
    image: {enabled: true, models: [minicpm]}
    video: {enabled: true, models: [minicpm]}
  output:
    audio:
      enabled: true
      auto: "off"
      mode: final
      models: [minimax, piper]
```

`models.yaml` 的条目名是可选择的模型实例，`backend` 是复用的代码实现，
`roles` 声明该实例可承担 `generation_model`、`asr` 或 `speech`，`input` 声明
`text/image/audio/video` 原生输入能力。模型路径、独立
Python 环境、设备、端点、超时及生成参数都保存在对应条目中；密钥仍只放环境变量。

本地 Provider 均为独立 HTTP 服务。Agent 中的 Qwen3-ASR 与 Piper 实现只是客户端，
不会加载权重或创建子进程。按模型名启动一个或多个服务：

```bash
bash ./llm_agent/scripts/start_models.sh minicpm piper
bash ./llm_agent/scripts/start_models.sh qwen3_asr minicpm piper
```

语音选择规则：

- `models` 是有序模型链，前一个模型不可创建或合成失败时尝试下一个；
- `auto: "off"` 仅响应显式 AUDIO 输出请求，`always` 始终朗读最终回答；
- `auto: inbound` 仅在本轮包含语音输入时朗读；
- 所有 TTS 失败时保留文字结果并报告部分失败。

MiniCPM 当前没有注册独立语音后端，因此不能放入输出模型链，也不会向 Omni Talker 发出请求。

环境变量覆盖：

```bash
export CAR_GENERATION_MODEL=minicpm
export CAR_SPEECH_MODELS=minimax,piper
```

MiniMax 密钥只能通过环境变量提供：

```bash
export MINIMAX_API_KEY='请替换为真实密钥'
```

模型 Provider 的自动化测试统一放在 `llm_agent/tests/`，不在 `scripts/`
维护重复测试入口。可运行相关测试：

```bash
llm_agent/py_env/venvs/agent/bin/python -m unittest \
  llm_agent.tests.test_asr \
  llm_agent.tests.test_model_providers \
  llm_agent.tests.test_provider_config
```

需要连同 ROS 接口和 Web Debug 一起验证时执行：

```bash
bash ./llm_agent/tests/run_tests.sh
```

常用组合：

```yaml
# 本地多模态 + Piper 本地语音
generation_model: minicpm
modalities: {output: {audio: {models: [piper]}}}
```

```yaml
# 本地多模态 + MiniMax 云端语音，失败回退 Piper
generation_model: minicpm
modalities: {output: {audio: {models: [minimax, piper]}}}
```

```yaml
# MiniMax 云端文本 + MiniMax 云端语音
generation_model: minimax
modalities: {output: {audio: {models: [minimax]}}}
```

## 标准输出

`ModelResponse` 包含文本和实际 generation provider；`SpeechResponse` 包含：

- `audio_wav`；
- 实际 speech provider；
- 采样率；
- 声道数。

所有语音 provider 必须返回非空、未压缩、16-bit PCM WAV。验证在发布 ROS 音频前完成，防止把 MP3、
空数据或损坏音频交给树莓派播放器。

## 增加新 Provider

1. 在 `models/providers/<provider>/` 实现 generation、ASR 或 speech；
2. 声明真实能力，不支持的模态必须在网络调用前拒绝；
3. 将厂商响应转换成 `ModelResponse` 或 `SpeechResponse`；
4. 在 `create_default_registry()` 显式注册；
5. 在 `config/models.yaml` 声明模型属性，在 `config/agent.yaml` 声明路由策略；
6. 添加参数映射、错误、超时、非法输出和回退测试。

MiniMax 文本接口参考：<https://platform.minimax.io/docs/api-reference/text-openai-api>；MiniMax T2A 接口
参考：<https://platform.minimax.io/docs/api-reference/speech-t2a-http>。
