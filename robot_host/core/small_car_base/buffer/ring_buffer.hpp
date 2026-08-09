/**
 * @file ring_buffer.hpp
 * @brief 不依赖 ROS 和媒体语义的固定容量环形缓冲。
 */
#pragma once

#include <algorithm>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace small_car {

/**
 * 固定容量环形缓冲。写满后覆盖最旧数据，适合保存短时间预录音或状态窗口。
 * 本类型不自动扩容，避免实时路径出现不可控的大块重新分配。
 */
template <typename T>
class RingBuffer {
 public:
  explicit RingBuffer(std::size_t capacity) : storage_(capacity) {
    if (capacity == 0) {
      throw std::invalid_argument("ring buffer capacity must be positive");
    }
  }

  std::size_t capacity() const { return storage_.size(); }
  std::size_t size() const { return size_; }
  bool empty() const { return size_ == 0; }

  void Clear() {
    begin_ = 0;
    size_ = 0;
  }

  /** 写入数据；超过容量时仅保留最新的 capacity 个元素。 */
  void Write(const T* data, std::size_t count) {
    if (data == nullptr && count != 0) {
      throw std::invalid_argument("ring buffer source is null");
    }
    if (count >= capacity()) {
      std::copy(data + (count - capacity()), data + count, storage_.begin());
      begin_ = 0;
      size_ = capacity();
      return;
    }
    for (std::size_t index = 0; index < count; ++index) {
      if (size_ < capacity()) {
        storage_[(begin_ + size_) % capacity()] = data[index];
        ++size_;
      } else {
        storage_[begin_] = data[index];
        begin_ = (begin_ + 1) % capacity();
      }
    }
  }

  /** 按时间顺序复制到调用方缓冲；通常只用于很小的预录音窗口。 */
  std::size_t CopyTo(T* destination, std::size_t destination_size) const {
    if (destination == nullptr && destination_size != 0) {
      throw std::invalid_argument("ring buffer destination is null");
    }
    const std::size_t count = std::min(size_, destination_size);
    for (std::size_t index = 0; index < count; ++index) {
      destination[index] = storage_[(begin_ + index) % capacity()];
    }
    return count;
  }

 private:
  std::vector<T> storage_;
  std::size_t begin_ = 0;
  std::size_t size_ = 0;
};

}  // namespace small_car
