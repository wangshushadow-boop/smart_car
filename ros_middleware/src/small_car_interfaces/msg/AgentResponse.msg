# 与请求一致的关联字段。
string request_id
string session_id

# completed、failed 或 cancelled。
string status

# 文本、语音、图片或视频等统一输出内容。
small_car_interfaces/AgentContent[] outputs

# 实际使用的模型和语音 Provider，便于诊断与展示。
string generation_provider
string speech_provider

# 稳定错误码和适合用户查看的错误说明；成功时为空。
string error_code
string error_message

# JSON 格式的耗时及模型扩展信息。
string metadata_json
