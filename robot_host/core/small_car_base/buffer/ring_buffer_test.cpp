#include "small_car_base/buffer/ring_buffer.hpp"

#include <array>
#include <cassert>

int main() {
  small_car::RingBuffer<int> buffer(4);
  const std::array<int, 3> first = {1, 2, 3};
  buffer.Write(first.data(), first.size());

  std::array<int, 4> output{};
  assert(buffer.CopyTo(output.data(), output.size()) == 3);
  assert(output[0] == 1 && output[1] == 2 && output[2] == 3);

  const std::array<int, 3> second = {4, 5, 6};
  buffer.Write(second.data(), second.size());
  assert(buffer.CopyTo(output.data(), output.size()) == 4);
  assert(output[0] == 3 && output[1] == 4 && output[2] == 5 && output[3] == 6);

  const std::array<int, 6> oversized = {7, 8, 9, 10, 11, 12};
  buffer.Write(oversized.data(), oversized.size());
  assert(buffer.CopyTo(output.data(), output.size()) == 4);
  assert(output[0] == 9 && output[1] == 10 && output[2] == 11 && output[3] == 12);
  return 0;
}
