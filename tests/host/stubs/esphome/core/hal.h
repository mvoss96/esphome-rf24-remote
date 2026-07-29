#pragma once

// A clock a test can set. That is the whole point of this file: the offline
// transition and the packet-id ageing behind it are timeouts, and on hardware
// they cost eighteen seconds of waiting per run. Here they are a line in a
// scenario - and the millis() wraparound, which no hardware run can reach at
// all, becomes an ordinary case.

#include <cstdint>

namespace esphome {

namespace stub_clock {
inline uint32_t &now_ms() {
  static uint32_t value = 0;
  return value;
}
}  // namespace stub_clock

inline uint32_t millis() { return stub_clock::now_ms(); }

// Time does not pass by itself here; a scenario says when it does.
inline void delay(uint32_t ms) { (void) ms; }

class GPIOPin {
 public:
  virtual ~GPIOPin() = default;
  virtual void setup() {}
  virtual void digital_write(bool value) { (void) value; }
  virtual bool digital_read() { return false; }
};

class InternalGPIOPin : public GPIOPin {};

}  // namespace esphome

#define IRAM_ATTR
