#pragma once

#include "esphome/core/hal.h"

#include <cstdint>
#include <string>

namespace esphome {

namespace setup_priority {
const float BUS = 1000.0f;
const float DATA = 600.0f;
const float LATE = -100.0f;
}  // namespace setup_priority

class Component {
 public:
  virtual ~Component() = default;
  virtual void setup() {}
  virtual void loop() {}
  virtual void dump_config() {}
  virtual float get_setup_priority() const { return setup_priority::DATA; }

  // The error state is a flag the harness can read back rather than a light on
  // a board.
  void status_set_error(const char *message = "unspecified") {
    this->error_ = true;
    this->error_message_ = message;
  }
  void status_clear_error() { this->error_ = false; }
  bool status_has_error() const { return this->error_; }
  const std::string &status_message() const { return this->error_message_; }

 protected:
  bool error_{false};
  std::string error_message_;
};

}  // namespace esphome
