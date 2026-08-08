/**
 * @file chassis_config.hpp
 * @brief 声明底盘参数 YAML 的读取、校验和批量下发接口。
 *
 * 参数文件是树莓派端的版本化参数源。程序启动时读取文件，再逐项写入 MCU
 * 并回读校验，避免主机与固件使用不一致的里程计和控制参数。
 */
#ifndef SMALL_CAR_BASE_CHASSIS_CHASSIS_CONFIG_HPP_
#define SMALL_CAR_BASE_CHASSIS_CHASSIS_CONFIG_HPP_

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace small_car {

class CarClient;

/** YAML 中一项可下发到底盘控制器的参数。 */
struct ChassisParameter {
  /** MCU 协议中的参数编号。 */
  std::uint8_t id = 0;
  /** YAML 键名，同时用于错误信息和回读校验。 */
  std::string name;
  /** 按协议保存的有符号 32 位整数值。 */
  std::int32_t value = 0;
};

/** 根据可执行文件位置推导同一部署目录中的默认参数文件路径。 */
std::string DefaultChassisConfigPath(const char* executable);

/**
 * @brief 读取并校验 ROS 2 格式的底盘参数文件。
 * @throws std::runtime_error 文件缺失、字段缺失、重复或数值越界时抛出。
 */
std::vector<ChassisParameter> LoadChassisConfig(const std::string& path);

/**
 * @brief 按 YAML 键名取得已校验参数值。
 * @throws std::runtime_error 参数集合中不存在指定名称时抛出。
 */
std::int32_t ChassisParameterValue(
    const std::vector<ChassisParameter>& parameters, std::string_view name);

/**
 * @brief 按名称和数值构造一项参数，并校验名称及合法范围。
 * @param error 校验失败时写入可读错误原因，可以为 nullptr。
 */
std::optional<ChassisParameter> MakeChassisParameter(
    std::string_view name, std::int32_t value, std::string* error);

/** @return 指定参数是否允许通过 ROS Parameter Server 临时调整。 */
bool IsRuntimeTunableChassisParameter(std::string_view name);

/**
 * @brief 下发一项参数并立即回读校验。
 * @param actual 回读成功时写入 MCU 实际值，可以为 nullptr。
 */
bool ApplyChassisParameter(CarClient* client,
                           const ChassisParameter& parameter,
                           std::chrono::milliseconds timeout,
                           std::int32_t* actual,
                           std::string* error);

/**
 * @brief 逐项下发参数并回读校验。
 * @param client 已打开串口的 MCU 客户端。
 * @param parameters 按顺序下发的参数集合。
 * @param timeout 每个参数等待回读的最长时间。
 * @param error 失败时写入可读错误原因，可以为 nullptr。
 * @return 全部参数写入且回读一致时返回 true。
 */
bool ApplyChassisConfig(CarClient* client,
                        const std::vector<ChassisParameter>& parameters,
                        std::chrono::milliseconds timeout,
                        std::string* error);

}  // namespace small_car

#endif  // SMALL_CAR_BASE_CHASSIS_CHASSIS_CONFIG_HPP_
