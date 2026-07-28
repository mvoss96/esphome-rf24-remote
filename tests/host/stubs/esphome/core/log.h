#pragma once

// Log macros that print one line per message, so a test can assert on the same
// text the firmware writes - the hardware benches already read the component's
// verdicts out of its log, and this keeps both phrased the same way.

#include <cstdarg>
#include <cstdio>
#include <cstring>

#define ESPHOME_LOG_LEVEL_NONE 0
#define ESPHOME_LOG_LEVEL_ERROR 1
#define ESPHOME_LOG_LEVEL_WARN 2
#define ESPHOME_LOG_LEVEL_INFO 3
#define ESPHOME_LOG_LEVEL_CONFIG 4
#define ESPHOME_LOG_LEVEL_DEBUG 5
#define ESPHOME_LOG_LEVEL_VERBOSE 6
#define ESPHOME_LOG_LEVEL_VERY_VERBOSE 7

#define ESPHOME_LOG_LEVEL ESPHOME_LOG_LEVEL_VERY_VERBOSE

namespace esphome {
namespace stub_log {

inline void write(const char *level, const char *format, ...) {
  std::printf("LOG %s ", level);
  va_list args;
  va_start(args, format);
  std::vprintf(format, args);
  va_end(args);
  std::printf("\n");
  std::fflush(stdout);
}

}  // namespace stub_log
}  // namespace esphome

// The tag is accepted and dropped: within one harness there is only one
// component, and carrying it would just make every expected line longer.
#define ESP_LOGE(tag, ...) ::esphome::stub_log::write("E", __VA_ARGS__)
#define ESP_LOGW(tag, ...) ::esphome::stub_log::write("W", __VA_ARGS__)
#define ESP_LOGI(tag, ...) ::esphome::stub_log::write("I", __VA_ARGS__)
#define ESP_LOGCONFIG(tag, ...) ::esphome::stub_log::write("C", __VA_ARGS__)
#define ESP_LOGD(tag, ...) ::esphome::stub_log::write("D", __VA_ARGS__)
#define ESP_LOGV(tag, ...) ::esphome::stub_log::write("V", __VA_ARGS__)
#define ESP_LOGVV(tag, ...) ::esphome::stub_log::write("VV", __VA_ARGS__)
