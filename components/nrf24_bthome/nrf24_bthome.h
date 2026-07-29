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
  // "B7:4F:E7:7F" - every log line this device writes carries it, because with
  // more than one registered sender a bare "Button 1: press" says nothing about
  // who pressed it.
  const char *sender_id_text() const { return this->sender_id_text_; }

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
  // Every measurement sensor is registered the same way, battery and voltage
  // included: they are BTHome objects like any other and had no business being
  // special cases. `index` selects which occurrence of that object in a frame
  // this sensor takes - the k-th object of a type addresses instance k, the
  // convention buttons and dimmers already follow.
  void add_object_sensor(uint8_t object_id, uint8_t index, sensor::Sensor *s) {
    this->object_sensors_.push_back(ObjectSensor{object_id, index, s, false, 0.0f});
  }
  void set_last_seen_sensor(sensor::Sensor *s) { this->last_seen_sensor_ = s; }
#endif
#ifdef USE_TEXT_SENSOR
  void set_name_text_sensor(text_sensor::TextSensor *s) { this->name_text_sensor_ = s; }
  // BTHome's text (0x53) and raw (0x54) objects, both [length][bytes]. Text goes
  // through as characters, raw as hex - the bytes are not a string and printing
  // them as one would cut the value at the first zero.
  void add_object_text_sensor(uint8_t object_id, uint8_t index, text_sensor::TextSensor *s) {
    this->object_text_sensors_.push_back(ObjectTextSensor{object_id, index, s, false, nullptr, 0});
  }
  void set_firmware_text_sensor(text_sensor::TextSensor *s) { this->firmware_text_sensor_ = s; }
  void set_sender_id_text_sensor(text_sensor::TextSensor *s) { this->sender_id_text_sensor_ = s; }
#endif

#ifdef USE_BINARY_SENSOR
  void set_connected_binary_sensor(binary_sensor::BinarySensor *s) { this->connected_sensor_ = s; }
  // A BTHome binary object - motion, door, smoke and the rest. One byte, 0 or 1,
  // and otherwise handled exactly like a measurement: buffered until the payload
  // has been read to the end, and addressed by instance.
  void add_object_binary_sensor(uint8_t object_id, uint8_t index, binary_sensor::BinarySensor *s) {
    this->object_binary_sensors_.push_back(ObjectBinarySensor{object_id, index, s, false, false});
  }
#endif
#ifdef USE_TIME
  void set_time(time::RealTimeClock *rtc) { this->rtc_ = rtc; }
#endif
  // Contact is considered lost after this quiet period (0 = never). Must
  // exceed the sender's periodic status interval.
  void set_timeout(uint32_t timeout_ms) { this->timeout_ms_ = timeout_ms; }

  // Publishes configuration-known values (sender ID); called once by the hub.
  void publish_static_info();

  // What this device is set up to receive. Worth printing because both halves
  // are misconfigurations that look like a dead radio from the outside: a
  // timeout shorter than the sender's status interval reports it offline
  // between broadcasts, and a platform entry that never attached shows up here
  // as a device with no entities at all.
  void dump_config() const;

  // Called periodically by the hub: after the quiet period it ages out the
  // packet-id dedup state and flips the connectivity sensor to offline.
  void check_timeout(uint32_t now_ms);

 protected:
  // What one payload turned out to contain. Nothing is published and no trigger
  // is fired while the objects are still being read, for two reasons that both
  // showed up in measurements:
  //
  //  - BTHome fixes no object order, and the packet id that identifies a repeat
  //    may sit BEHIND the event object it belongs to. Acting as the objects go
  //    past therefore fired a repeat's button before the id could suppress it -
  //    two events for one press, reproduced by sending one frame twice.
  //  - A payload whose objects do not add up may have been read with the wrong
  //    length, and the remainder then decodes into something plausible rather
  //    than into an obvious error. Values from such a frame are not worth
  //    publishing and its events did not happen.
  //
  // Capacity is fixed: this runs off a frame buffer in the radio's drain loop,
  // and 32 bytes cannot hold more objects than this anyway.
  // constexpr, not const: it is passed to a log call, which odr-uses it, and a
  // plain static const member would then need an out-of-line definition.
  static constexpr uint8_t MAX_EVENTS = 12;
  struct Pending {
    // Event codes in the order they appeared; the k-th entry addresses
    // instance k, and a None entry is a placeholder that fires nothing.
    uint8_t buttons[MAX_EVENTS];
    uint8_t button_count{0};
    uint8_t dimmer_events[MAX_EVENTS];
    uint8_t dimmer_steps[MAX_EVENTS];
    uint8_t dimmer_count{0};
    bool overflow{false};  // more event objects than MAX_EVENTS

    int16_t packet_id{-1};  // -1 = the payload carried none
    // Points into the caller's frame buffer, which outlives this struct: it is
    // only read before handle_service_data() returns.
    const uint8_t *name{nullptr};
    uint8_t name_len{0};
    bool has_firmware{false};
    bool firmware_u32{false};
    uint32_t firmware{0};
  };
  void commit_(const Pending &pending);

  std::array<uint8_t, 4> sender_id_{{0, 0, 0, 0}};
  char sender_id_text_[12]{"00:00:00:00"};
  int16_t last_packet_id_{-1};  // -1 = nothing received yet
  bool warned_no_packet_id_{false};
  uint32_t timeout_ms_{0};
  uint32_t last_contact_ms_{0};  // millis() of the last valid frame (repeats count)
  bool ever_seen_{false};
  std::vector<Trigger<uint8_t, std::string> *> button_triggers_;
  std::vector<Trigger<uint8_t, int> *> dimmer_triggers_;
#ifdef USE_SENSOR
  // The value carried by the current payload is parked in the slot itself
  // rather than in Pending: one payload is processed at a time, and this keeps
  // a per-frame struct from growing with the number of configured sensors.
  struct ObjectSensor {
    uint8_t object_id;
    uint8_t index;  // 1-based occurrence of that object id within one payload
    sensor::Sensor *sensor;
    bool has_pending;
    float pending;
  };
  std::vector<ObjectSensor> object_sensors_;
  sensor::Sensor *last_seen_sensor_{nullptr};
#endif
#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *name_text_sensor_{nullptr};
  text_sensor::TextSensor *firmware_text_sensor_{nullptr};
  text_sensor::TextSensor *sender_id_text_sensor_{nullptr};
  struct ObjectTextSensor {
    uint8_t object_id;
    uint8_t index;  // 1-based occurrence of that object id within one payload
    text_sensor::TextSensor *sensor;
    bool has_pending;
    // Into the caller's frame buffer, which outlives the parse: read once in
    // commit_(), which still runs inside handle_service_data().
    const uint8_t *bytes;
    uint8_t length;
  };
  std::vector<ObjectTextSensor> object_text_sensors_;
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *connected_sensor_{nullptr};
  struct ObjectBinarySensor {
    uint8_t object_id;
    uint8_t index;  // 1-based occurrence of that object id within one payload
    binary_sensor::BinarySensor *sensor;
    bool has_pending;
    bool pending;
  };
  std::vector<ObjectBinarySensor> object_binary_sensors_;
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
