#pragma once

#include <string>

namespace esphome {

// Virtual where ESPHome's is not: the harness needs to see what a trigger was
// fired with, and overriding is the least intrusive way to watch it. Firing
// itself is the component's business either way.
template<typename... Ts> class Trigger {
 public:
  virtual ~Trigger() = default;
  virtual void trigger(Ts... x) { (void) std::initializer_list<int>{((void) x, 0)...}; }
};

}  // namespace esphome
