# MiniCPM-o AWQ 原生语音服务

当前方案在 RTX 3090 24GB 上运行 `MiniCPM-o-4_5-AWQ`，由 vLLM-Omni 的三个阶段完成
多模态理解、语音编码和 24 kHz 波形生成。

## 环境与模型

```text
复用虚拟环境：/opt/minicpm-service/venv
AWQ 模型：    /mnt/d/AI/models/MiniCPM-o-4_5-AWQ
服务地址：    http://127.0.0.1:8099
语音 WebSocket：ws://127.0.0.1:8099/v1/audio/speech/stream
3090 配置：   llm_agent/config/minicpmo_4_5_awq_3090.yaml
```

脚本直接调用虚拟环境中的程序，正常启动不需要手工激活。需要手动执行 `python`、`pip`、
`vllm-omni` 或排查依赖时，可以复用同一环境：

```zsh
source /opt/minicpm-service/venv/bin/activate
```

不要同时运行 8000 端口的普通 vLLM；RTX 3090 无法让两个服务同时驻留。

## 国内下载源优先

Python 包优先使用清华 PyPI：

```zsh
/opt/minicpm-service/venv/bin/pip install \
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
/opt/minicpm-service/venv/bin/pip install \
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

## 生成测试语音

```zsh
/opt/minicpm-service/venv/bin/python scripts/test_minicpm_omni_audio.py
```

默认生成：

```text
/tmp/minicpm_omni_test.wav
```

可以用环境变量修改文本和输出路径：

```zsh
MINICPM_OMNI_TEST_TEXT='小车语音测试' \
MINICPM_OMNI_TEST_WAV=/tmp/car_test.wav \
/opt/minicpm-service/venv/bin/python scripts/test_minicpm_omni_audio.py
```

测试脚本通过 WebSocket 接收模型原生 WAV。Agent 后续将得到的 WAV 发布到树莓派音频输出 topic，
由 `robot_host` 的播放节点输出到 Jabra。

## 已验证结果

- AWQ 权重由 AutoAWQ Marlin 内核加载；
- Stage 0、Stage 1、Stage 2 均能在 RTX 3090 24GB 上驻留；
- 完成一次语音生成后的显存占用约 23.9GB，3090 基本满载，不能再并行启动其他 GPU 模型；
- 已实际生成 24 kHz WAV，测试文件约 3.94MB。
