# Agent 内容类型。统一消息允许一次请求或响应携带多个不同模态的内容块。
uint8 TEXT=1
uint8 AUDIO=2
uint8 IMAGE=3
uint8 VIDEO=4
uint8 JSON=5

# 当前内容块的类型，必须是上面定义的常量之一。
uint8 content_type

# 内容名称，用于区分多个附件，例如 front_camera 或 user_speech。
string name

# 标准 MIME 类型，例如 text/plain、audio/wav、image/jpeg、video/mp4。
string mime_type

# 文本和 JSON 内容直接放在这里；二进制模态使用 data。
string text

# 小型音频、压缩图像或视频内容。大型媒体应使用 uri 或 topic 引用。
uint8[] data

# 可由 Agent 所在主机访问的媒体地址；为空表示没有 URI 引用。
string uri

# 实时媒体的 ROS topic；为空表示内容不是实时流引用。
string topic

# JSON 格式的模态元数据，例如采样率、声道数、宽高或帧率。
string metadata_json
