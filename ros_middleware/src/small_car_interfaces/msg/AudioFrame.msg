# 音频帧第一个采样点的采集时间，而不是消息发布时间。
std_msgs/Header header

# 每秒采样点数，例如 16000。
uint32 sample_rate

# 声道数量；小车语音链路默认使用单声道。
uint8 channels

# 样本编码，例如 pcm_s16le。
string encoding

# 每个声道在本帧内的采样点数，例如 20 ms @ 16 kHz 为 320。
uint32 frame_samples

# 按 encoding 编码的交错音频字节。
uint8[] data
