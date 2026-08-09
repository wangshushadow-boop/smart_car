#include "agent_client/camera_sampler.hpp"

#include <utility>

namespace agent_client {

void CameraSampler::Store(sensor_msgs::msg::CompressedImage::UniquePtr message) {
  if (!message || message->data.empty()) {
    return;
  }
  std::lock_guard<std::mutex> lock(mutex_);
  latest_ = std::move(message);
}

std::vector<std::uint8_t> CameraSampler::TakeLatest() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!latest_) {
    return {};
  }
  auto data = std::move(latest_->data);
  latest_.reset();
  return data;
}

}  // namespace agent_client
