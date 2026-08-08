# Agent 音视频语音闭环

完整链路如下：树莓派采集 Jabra 麦克风和摄像头，ROS 2 把音视频发送到 WSL；Agent 在语音结束时
调用 MiniCPM-o 4.5 Omni，并把生成的原生语音回传到树莓派播放。

```text
树莓派 Jabra 麦克风、摄像头
  → /car/audio/input、/car/camera/image/compressed
  → WSL VAD 与 Agent
  → MiniCPM-o Omni（127.0.0.1:8099）
  → /car/audio/output
  → 树莓派 Jabra 扬声器
```

## 运行前条件

- 树莓派和 WSL 能互相访问，且 DDS UDP 没有被防火墙隔离；
- 两端 `ROS_DOMAIN_ID` 均为 `0`；
- WSL 已在 `robot_host` 中构建并 source `small_car_interfaces`；
- 默认模型路径为 `/mnt/d/AI/models/MiniCPM-o-4_5-AWQ`。

## 树莓派：启动音视频和播放节点

仓库容器会通过 `pi_av.launch.py` 同时启动摄像头、麦克风发布节点和扬声器播放节点：

```bash
cd ~/smart_car/robot_host
docker compose -f ros2/compose.yaml up --build -d
docker compose -f ros2/compose.yaml logs -f small_car_ros2
```

容器内检查输入 topic：

```bash
ros2 topic hz /car/audio/input
ros2 topic hz /car/camera/image/compressed
```

## WSL 终端 1：启动 Omni

```zsh
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_minicpm_omni.sh
```

保持终端打开。另开终端检查服务：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8099/health
curl --noproxy '*' -fsS http://127.0.0.1:8099/v1/models
```

## WSL 终端 2：启动 Agent

```zsh
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_agent.sh
```

看到下面日志后，对麦克风说话并保持约一秒静音：

```text
Agent 已启动：订阅树莓派音视频，并回传模型语音
```

Agent 会打印文本回复，随后树莓派的 Jabra 扬声器播放模型语音。播放期间 Agent 会暂停接收麦克风，
并在结束后额外等待 500 ms，以降低扬声器回声再次触发 VAD 的概率。

## 逐段验证

WSL 应发现树莓派输入：

```zsh
ros2 topic list | grep '^/car/'
ros2 topic hz /car/audio/input
```

模型回答时，树莓派应收到输出：

```bash
ros2 topic hz /car/audio/output
```

单独验证树莓派声卡：

```bash
aplay -D plughw:CARD=USB,DEV=0 /usr/share/sounds/alsa/Front_Center.wav
```

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `curl` 返回 502 | 代理拦截了本机地址；保留 `--noproxy '*'`。 |
| Agent 一直等待语音 | 在两端检查 `/car/audio/input`；确认 `ROS_DOMAIN_ID=0` 并放行 DDS UDP。 |
| 有文本但没有声音 | 在树莓派检查 `/car/audio/output`，再用上述 `aplay` 命令验证声卡名称。 |
| VAD 不触发或误触发 | 调整 `vad_energy_threshold`、`vad_min_speech_ms` 和 `vad_silence_ms`。 |
| 模型请求返回 502 | 更新 Agent 后重启；客户端会强制绕过 WSL HTTP 代理。 |

输入 WAV 以内嵌 data URL 发送，不会在磁盘上留下临时音频文件。
