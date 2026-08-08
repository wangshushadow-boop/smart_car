# Agent 音视频语音闭环

完整链路如下：树莓派采集 Jabra 麦克风和摄像头，ROS 2 把音视频发送到 WSL；Agent 在语音结束时
调用 MiniCPM-o 4.5 Omni 完成意图识别和回复生成，再由 Piper 合成语音并回传树莓派播放。

```text
树莓派 Jabra 麦克风、摄像头
  → /car/audio/input、/car/camera/image/compressed
  → WSL VAD、回声抑制与 SpeechFinished 事件
  → LangGraph：意图识别 → 白名单工具（可选）→ 回复
  → MiniCPM-o Omni（127.0.0.1:8099）+ Piper TTS
  → /car/audio/output
  → 树莓派 Jabra 扬声器
```

## 运行前条件

- 树莓派和 WSL 能互相访问，且 DDS UDP 没有被防火墙隔离；
- 两端 `ROS_DOMAIN_ID` 均为 `0`；
- WSL 已构建并 source `ros_middleware` 中的 `small_car_interfaces`；
- 默认模型路径为 `/mnt/d/AI/models/MiniCPM-o-4_5-AWQ`。

## 树莓派：启动音视频和播放节点

仓库容器会通过 `pi_av.launch.py` 同时启动摄像头、麦克风发布节点和扬声器播放节点：

```bash
cd ~/smart_car/robot_host
docker compose -f ros_middleware/docker/compose.yaml up --build -d
docker compose -f ros_middleware/docker/compose.yaml logs -f small_car_ros2
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

Agent 会打印文本回复，随后树莓派的 Jabra 扬声器播放 Piper 合成的语音。播放期间麦克风采集保持
开启，参考信号消除器会抑制扬声器回声；检测到独立的人声时会发布停止播放事件，实现 barge-in。
播放正常结束后保留约 500 ms 的回声尾音保护。

一轮普通问答目前包含两次模型调用：第一次只输出结构化意图，第二次生成面向用户的回复。
状态查询还会在两次调用之间经过工具白名单检查。当前 `get_robot_status` 尚未接入 ROS 状态网关，
因此会如实返回不可用；动作请求会直接回复“尚未开放”，不会下发底盘控制。

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
| 询问车辆状态时返回不可用 | 阶段 1～5 的预期行为；等待 ROS `VehicleGateway` 接入真实状态。 |

输入 WAV 以内嵌 data URL 发送，不会在磁盘上留下临时音频文件。

## Agent 单元测试

在仓库根目录执行：

```zsh
/opt/minicpm-service/venv/bin/python -m unittest discover -s llm_agent/tests -v
```

测试使用假模型和假状态提供者，不要求启动 GPU 模型或连接树莓派。
