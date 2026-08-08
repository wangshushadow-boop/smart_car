# 模型 Provider

## 两类独立接口

Agent 将理解/回复和语音合成分成两个接口：

```text
GenerationBackend 处理文本、图像、音频输入并返回最终文本
SpeechBackend     接收最终文本并返回标准 WAV
```

两者可以来自不同 provider。例如使用本地 MiniCPM 理解摄像头与麦克风，同时使用 MiniMax 云端语音；
也可以使用 MiniMax 文本模型和本地 Piper。Agent 图和 ROS 输出不依赖具体厂商。

## 当前 Provider

| Provider | 文本生成 | 图像输入 | 音频输入 | 语音输出 |
| --- | ---: | ---: | ---: | ---: |
| `minicpm` | 是 | 是 | 是 | 本地 Omni WAV |
| `minimax` | 是 | 否 | 否 | 云端 T2A WAV |
| `piper` | 不适用 | 不适用 | 不适用 | 本地 WAV |

MiniMax 的 OpenAI 兼容文本接口当前不接受图像或音频。选择 `generation.provider=minimax` 后，文本事件
可以正常工作；直接把 `SpeechFinished` 的 WAV 交给它会在发出网络请求前被拒绝。完整的云端语音对话
还需要后续增加 ASR/转写 provider，或由本地 MiniCPM 先产生转写。

## 配置

默认配置位于 `llm_agent/config/agent.yaml`：

```yaml
generation:
  provider: minicpm

speech:
  provider: auto
  preferred: same_provider
  fallback: piper
```

语音选择规则：

- `piper`、`minicpm`、`minimax`：严格使用指定 provider，失败时保留文本并报告 TTS 错误；
- `native` 或 `same_provider`：严格使用 generation provider 的语音能力；
- `auto`：优先 `preferred`，不可创建或合成失败时使用 `fallback`。

环境变量覆盖：

```bash
export CAR_GENERATION_PROVIDER=minicpm
export CAR_SPEECH_PROVIDER=auto
```

MiniMax 密钥只能通过环境变量提供：

```bash
export MINIMAX_API_KEY='请替换为真实密钥'
```

可独立验证某个语音 provider，不启动 ROS：

```bash
/opt/minicpm-service/venv/bin/python -m llm_agent.scripts.test_speech_provider \
  --provider minicpm
```

增加 `--output /tmp/speech.wav` 可以保存测试 WAV；不指定时只在内存中验证并打印格式信息。

常用组合：

```yaml
# 本地多模态 + 本地原生语音，失败回退 Piper
generation: {provider: minicpm}
speech: {provider: auto, preferred: same_provider, fallback: piper}
```

```yaml
# 本地多模态 + MiniMax 云端语音，失败回退 Piper
generation: {provider: minicpm}
speech: {provider: auto, preferred: minimax, fallback: piper}
```

```yaml
# MiniMax 云端文本 + MiniMax 云端语音
generation: {provider: minimax}
speech: {provider: minimax, preferred: same_provider, fallback: piper}
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

1. 在 `models/<provider>/` 实现 generation 和/或 speech；
2. 声明真实能力，不支持的模态必须在网络调用前拒绝；
3. 将厂商响应转换成 `ModelResponse` 或 `SpeechResponse`；
4. 在 `create_default_registry()` 显式注册；
5. 在 `config/agent.yaml` 添加不含密钥的参数；
6. 添加参数映射、错误、超时、非法输出和回退测试。

MiniMax 文本接口参考：<https://platform.minimax.io/docs/api-reference/text-openai-api>；MiniMax T2A 接口
参考：<https://platform.minimax.io/docs/api-reference/speech-t2a-http>。
