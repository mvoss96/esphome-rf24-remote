#pragma once

#include <cstdio>
#include <string>

namespace esphome {
namespace binary_sensor {

// Deliberately without ESPHome's publish-on-change filter: what the component
// decides to publish is what this has to show. Whether an unchanged state
// reaches Home Assistant is the platform's business, and the radio bench checks
// that end of it.
class BinarySensor {
 public:
  explicit BinarySensor(std::string name) : name_(std::move(name)) {}

  void publish_state(bool state) {
    this->state = state;
    this->has_state_ = true;
    std::printf("PUBLISH %s %s\n", this->name_.c_str(), state ? "ON" : "OFF");
    std::fflush(stdout);
  }
  bool has_state() const { return this->has_state_; }
  const std::string &get_name() const { return this->name_; }

  bool state{false};

 protected:
  std::string name_;
  bool has_state_{false};
};

}  // namespace binary_sensor
}  // namespace esphome
