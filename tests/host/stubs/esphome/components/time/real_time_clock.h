#pragma once

#include <cstdint>

namespace esphome {
namespace time {

struct ESPTime {
  uint32_t timestamp{0};
  bool valid{false};
  bool is_valid() const { return this->valid; }
};

// A clock a scenario sets, and can also leave invalid - which is a case worth
// having: before Home Assistant has answered, last_seen must publish nothing
// rather than publish zero.
class RealTimeClock {
 public:
  void set_now(uint32_t epoch, bool valid = true) {
    this->now_.timestamp = epoch;
    this->now_.valid = valid;
  }
  ESPTime utcnow() const { return this->now_; }

 protected:
  ESPTime now_{};
};

}  // namespace time
}  // namespace esphome
