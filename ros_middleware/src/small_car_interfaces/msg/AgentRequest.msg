# 调用方生成的全局唯一请求 ID，用于日志、去重和结果关联。
string request_id

# 会话 ID；同一会话的多轮请求使用相同值。
string session_id

# 请求来源，例如 raspberry_pi、web_debug 或 integration_test。
string source

# 请求创建时间。
builtin_interfaces/Time created_at

# 一次请求可以组合文本、音频、图片、视频和结构化上下文。
small_car_interfaces/AgentContent[] inputs

# 期望输出模态，例如 text、audio、image、video。
string[] response_modalities

# 是否允许本轮调用白名单工具。
bool allow_tools

# JSON 格式的扩展参数，不用于承载大块媒体内容。
string metadata_json
