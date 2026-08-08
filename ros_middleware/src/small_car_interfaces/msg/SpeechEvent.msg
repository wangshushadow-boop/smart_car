# 一句话结束时由 ROS 感知层发布，供 llm_agent 订阅。
std_msgs/Header header

# 语音发生时最近的一帧压缩图像；没有图像时 data 为空。
sensor_msgs/CompressedImage image

# 本次语音拼接后的 PCM 音频。header.stamp 是第一个采样点的时间。
small_car_interfaces/AudioFrame speech_audio
