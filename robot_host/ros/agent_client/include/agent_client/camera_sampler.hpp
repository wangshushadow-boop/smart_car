/** @file camera_sampler.hpp @brief 仅持有最新压缩图像所有权的采样器。 */
#pragma once

#include <memory>
#include <mutex>
#include <vector>

#include <sensor_msgs/msg/compressed_image.hpp>

namespace agent_client {

class CameraSampler {
 public:
  void Store(sensor_msgs::msg::CompressedImage::UniquePtr message);

  /** 移动最新 JPEG 数据；没有图像时返回空 vector。 */
  std::vector<std::uint8_t> TakeLatest();

 private:
  std::mutex mutex_;
  sensor_msgs::msg::CompressedImage::UniquePtr latest_;
};

}  // namespace agent_client
