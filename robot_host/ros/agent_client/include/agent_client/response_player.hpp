/** @file response_player.hpp @brief 将播放 Service 接收的 WAV 交给 Core ALSA。 */
#pragma once

#include <atomic>
#include <functional>
#include <string>
#include <thread>
#include <vector>

namespace agent_client {

class ResponsePlayer {
 public:
  using ErrorHandler = std::function<void(const std::string&)>;

  ResponsePlayer(std::string device, ErrorHandler error_handler);
  ~ResponsePlayer();

  ResponsePlayer(const ResponsePlayer&) = delete;
  ResponsePlayer& operator=(const ResponsePlayer&) = delete;

  void Play(std::vector<std::uint8_t> wav);
  bool playing() const { return playing_.load(); }
  void Stop();

 private:
  void Run(std::vector<std::uint8_t> wav);

  std::string device_;
  ErrorHandler error_handler_;
  std::atomic<bool> playing_{false};
  std::atomic<bool> stop_requested_{false};
  std::thread thread_;
};

}  // namespace agent_client
