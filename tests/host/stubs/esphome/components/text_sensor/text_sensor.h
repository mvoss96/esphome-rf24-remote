#pragma once

#include <cstdio>
#include <string>

namespace esphome {
namespace text_sensor {

// Quoted on output: a text object may be empty or carry spaces, and an
// unquoted empty line would be indistinguishable from no publish at all.
class TextSensor {
 public:
  explicit TextSensor(std::string name) : name_(std::move(name)) {}

  void publish_state(const std::string &value) {
    this->state = value;
    this->has_state_ = true;
    std::printf("PUBLISH %s '%s'\n", this->name_.c_str(), value.c_str());
    std::fflush(stdout);
  }
  bool has_state() const { return this->has_state_; }
  const std::string &get_name() const { return this->name_; }

  std::string state;

 protected:
  std::string name_;
  bool has_state_{false};
};

}  // namespace text_sensor
}  // namespace esphome
