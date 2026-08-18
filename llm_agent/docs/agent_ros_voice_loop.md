# Agent 多模态语音闭环

树莓派负责设备和交互聚合，WSL Agent 提供短 DialogueLoop Service：

```text
树莓派麦克风和摄像头
  → 设备侧 VAD + 最近 JPEG
  → RunAgent Service（audio/wav + image/jpeg）
  → DialogueLoop 快速响应或提交后台 Skill
  → /car/audio/enqueue 主动下发语音
  → 树莓派后台播放
```

## 启动顺序

WSL 终端 1：

```bash
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_minicpm_omni.sh
```

WSL 终端 2：

```bash
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_agent.sh
```

树莓派容器会通过 `agent_client.launch.py` 启动摄像头和统一 C++ Agent Client。音频采集、VAD
缓冲及播放都在该客户端进程内完成，不通过音频 Topic：

```bash
docker compose -f ros_middleware/docker/compose.yaml up --build -d
```

## 检查

```bash
ros2 service list -t | grep /car/agent/run
ros2 service type /car/agent/run
ros2 node info /car_agent_client
ros2 topic hz /car/camera/image/compressed
```

树莓派客户端每次只允许一个语音请求。当前设备侧没有 AEC，播放 Agent 语音时暂停 VAD，并保留 500 ms
尾音保护，避免把扬声器内容循环送回 Agent。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| Agent Service 不可用 | 检查两端 `ROS_DOMAIN_ID=0`、DDS 实现和防火墙 |
| 请求被拒绝 | 检查内容类型、空输入和 64 MiB 内联限制 |
| 有文字没有声音 | 确认请求包含 `audio` 输出模态并检查 Piper 配置 |
| MiniMax 拒绝图片或音频 | 当前 MiniMax 文本 Provider 不声明这些输入能力 |
| MiniCPM Stage 1 条件张量错误 | 停止旧客户端并重启 Omni；当前 Agent 不再调用独立 Talker |

## 测试

```bash
./scripts/build_ros_interfaces.sh
./scripts/test_agent.sh
```
