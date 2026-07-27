#pragma once

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/hal.h"
#include "esphome/components/nrf24/nrf24.h"
#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif
#ifdef USE_TEXT_SENSOR
#include "esphome/components/text_sensor/text_sensor.h"
#endif
#ifdef USE_BINARY_SENSOR
#include "esphome/components/binary_sensor/binary_sensor.h"
#endif
#ifdef USE_TIME
#include "esphome/components/time/real_time_clock.h"
#endif

#include <array>
#include <string>
#include <vector>

namespace esphome {
namespace nrf24_bthome {

class NRF24BTHomeDevice;

// Receives BTHome-over-nRF24 broadcasts: frames of
// [4-byte sender ID][BTHome v2 service data] sent NO_ACK to a shared
// broadcast address. The radio itself is owned by the generic nrf24
// component; this hub is a frame listener that decodes BTHome and routes
// to the registered devices.
class NRF24BTHomeHub : public Component, public nrf24::NRF24Listener {
 public:
  void set_nrf24_parent(nrf24::NRF24Hub *parent) { this->parent_ = parent; }
  void register_device(NRF24BTHomeDevice *device) { this->devices_.push_back(device); }

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  void on_nrf24_frame(uint8_t pipe, const uint8_t *data, uint8_t len, bool padded) override;

 protected:
  nrf24::NRF24Hub *parent_{nullptr};
  uint32_t last_timeout_check_ms_{0};  // throttle for the per-device offline sweep
  std::vector<NRF24BTHomeDevice *> devices_;
};

// One remote, identified by its 4-byte sender ID. Dedupes the sender's
// NO_ACK repeats via the BTHome packet id and fires the automation
// triggers / updates the sensors registered on it.
class NRF24BTHomeDevice {
 public:
  void set_sender_id(const std::vector<uint8_t> &id);
  bool matches(const uint8_t *id) const;
  const uint8_t *sender_id() const { return this->sender_id_.data(); }

  void add_button_trigger(Trigger<uint8_t, std::string> *trigger) {
    this->button_triggers_.push_back(trigger);
  }
  void add_dimmer_trigger(Trigger<uint8_t, int> *trigger) {
    this->dimmer_triggers_.push_back(trigger);
  }

  // Called by the hub with the service-data part of a frame (after the
  // sender ID matched). Returns false if the packet was a dedup repeat.
  bool handle_service_data(const uint8_t *data, size_t len);

#ifdef USE_SENSOR
  void set_battery_sensor(sensor::Sensor *s) { this->battery_sensor_ = s; }
  void set_voltage_sensor(sensor::Sensor *s) { this->voltage_sensor_ = s; }
  void set_last_seen_sensor(sensor::Sensor *s) { this->last_seen_sensor_ = s; }
#endif
#ifdef USE_TEXT_SENSOR
  void set_name_text_sensor(text_sensor::TextSensor *s) { this->name_text_sensor_ = s; }
  void set_firmware_text_sensor(text_sensor::TextSensor *s) { this->firmware_text_sensor_ = s; }
  void set_sender_id_text_sensor(text_sensor::TextSensor *s) { this->sender_id_text_sensor_ = s; }
#endif

#ifdef USE_BINARY_SENSOR
  void set_connected_binary_sensor(binary_sensor::BinarySensor *s) { this->connected_sensor_ = s; }
#endif
#ifdef USE_TIME
  void set_time(time::RealTimeClock *rtc) { this->rtc_ = rtc; }
#endif
  // Contact is considered lost after this quiet period (0 = never). Must
  // exceed the sender's periodic status interval.
  void set_timeout(uint32_t timeout_ms) { this->timeout_ms_ = timeout_ms; }

  // Publishes configuration-known values (sender ID); called once by the hub.
  void publish_static_info();

  // Called periodically by the hub: after the quiet period it ages out the
  // packet-id dedup state and flips the connectivity sensor to offline.
  void check_timeout(uint32_t now_ms);

 protected:
  std::array<uint8_t, 4> sender_id_{{0, 0, 0, 0}};
  int16_t last_packet_id_{-1};  // -1 = nothing received yet
  uint32_t timeout_ms_{0};
  uint32_t last_contact_ms_{0};  // millis() of the last valid frame (repeats count)
  bool ever_seen_{false};
  std::vector<Trigger<uint8_t, std::string> *> button_triggers_;
  std::vector<Trigger<uint8_t, int> *> dimmer_triggers_;
#ifdef USE_SENSOR
  sensor::Sensor *battery_sensor_{nullptr};
  sensor::Sensor *voltage_sensor_{nullptr};
#endif
#ifdef USE_SENSOR
  sensor::Sensor *last_seen_sensor_{nullptr};
#endif
#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *name_text_sensor_{nullptr};
  text_sensor::TextSensor *firmware_text_sensor_{nullptr};
  text_sensor::TextSensor *sender_id_text_sensor_{nullptr};
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *connected_sensor_{nullptr};
#endif
#ifdef USE_TIME
  time::RealTimeClock *rtc_{nullptr};
#endif
};

class ButtonTrigger : public Trigger<uint8_t, std::string> {
 public:
  explicit ButtonTrigger(NRF24BTHomeDevice *device) { device->add_button_trigger(this); }
};

class DimmerTrigger : public Trigger<uint8_t, int> {
 public:
  explicit DimmerTrigger(NRF24BTHomeDevice *device) { device->add_dimmer_trigger(this); }
};

}  // namespace nrf24_bthome
}  // namespace esphome
