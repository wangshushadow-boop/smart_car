# 独立全模态 Agent Web Debug

本模块只通过 `/car/agent/run` ROS 2 Action 调试 Agent，不导入 Runtime、LangGraph、模型、工具或 TTS。

```bash
cd /mnt/d/work/smart_car
./agent_debug_web/scripts/start_debug_web.sh
```

浏览器打开 `http://127.0.0.1:8765`，可以组合提交文字、音频、图片和视频，并选择是否返回语音。
服务没有鉴权，只允许监听本机回环地址。

动作请求会显示 `small_car.motion.v1` JSON 预览，但 Web Debug 不执行车辆动作。只有树莓派
`agent_client` 作为请求方收到任务时，才会经过本地二次校验并调用 Nav2，避免调试页面意外控制实车。
