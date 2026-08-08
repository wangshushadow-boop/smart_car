/**
 * @file serial_port.hpp
 * @brief 声明 Linux 串口的轻量级 RAII 封装。
 *
 * SerialPort 负责设备打开、termios 参数配置和原始字节收发，不理解小车协议。
 * 对象不可复制，析构时会自动关闭文件描述符。
 */
#ifndef SMALL_CAR_BASE_TRANSPORT_SERIAL_PORT_HPP_
#define SMALL_CAR_BASE_TRANSPORT_SERIAL_PORT_HPP_

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace small_car {

/** Linux 非阻塞串口封装。当前实现不保证多个线程同时调用的安全性。 */
class SerialPort {
 public:
  SerialPort() = default;
  /** 自动关闭仍处于打开状态的设备。 */
  ~SerialPort();

  SerialPort(const SerialPort&) = delete;
  SerialPort& operator=(const SerialPort&) = delete;

  /**
   * @brief 打开并配置串口。
   * @param device Linux 设备路径，例如 /dev/ttyACM0。
   * @param baudrate 波特率，目前仅接受实现中列出的标准速率。
   * @return 打开并配置成功返回 true，否则返回 false。
   */
  bool Open(const std::string& device, int baudrate);
  /** 关闭串口；未打开时调用不会产生副作用。 */
  void Close();
  /** @return 文件描述符有效时返回 true。 */
  bool IsOpen() const;

  /**
   * @brief 非阻塞读取当前已经到达的字节。
   * @return 读取到的数据；无数据或遇到可恢复错误时返回空数组。
   */
  std::vector<std::uint8_t> Read(std::size_t max_size);
  /** @return 所有字节完整写出时返回 true。 */
  bool Write(const std::vector<std::uint8_t>& data);

 private:
  /** Linux 文件描述符，-1 表示设备未打开。 */
  int fd_ = -1;
};

}  // namespace small_car

#endif  // SMALL_CAR_BASE_TRANSPORT_SERIAL_PORT_HPP_
