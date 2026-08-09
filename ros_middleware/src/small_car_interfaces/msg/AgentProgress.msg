# 请求关联 ID。
string request_id

# queued、understanding、tool_running、generating、synthesizing 等阶段。
string stage

# 0～100 的粗粒度完成百分比。
uint8 percent

# 面向调用方的中文进度说明。
string message

# 可选的流式文本、音频或其他部分结果。
small_car_interfaces/AgentContent[] partial_outputs
