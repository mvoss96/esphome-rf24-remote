#pragma once

#include <cstdio>
#include <string>

namespace esphome {
namespace sensor {

// Publishing prints. Values go out with six decimals rather than the entity's
// configured accuracy: how many places Home Assistant shows is decided by the
// Python table and checked over the air, whereas what matters here is the
// number the component computed.
class Sensor {
 public:
  explicit Sensor(std::string name) : name_(std::move(name)) {}

  void publish_state(float state) {
    this->state = state;
    this->has_state_ = true;
    std::printf("PUBLISH %s %.6f\n", this->name_.c_str(), state);
    std::fflush(stdout);
  }
  bool has_state() const { return this->has_state_; }
  const std::string &get_name() const { return this->name_; }

  float state{0.0f};

 protected:
  std::string name_;
  bool has_state_{false};
};

}  // namespace sensor
}  // namespace esphome
