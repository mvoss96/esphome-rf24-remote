#pragma once

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/hal.h"
#include "esphome/components/spi/spi.h"
#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif
#ifdef USE_TEXT_SENSOR
#include "esphome/components/text_sensor/text_sensor.h"
#endif

#include <array>
#include <string>
#include <vector>

namespace esphome {
namespace nrf24_bthome {

class NRF24BTHomeDevice;

// Receives BTHome-over-nRF24 broadcasts: frames of
// [4-byte sender ID][BTHome v2 service data] sent NO_ACK to a shared
// broadcast address. Talks to the nRF24L01 directly over ESPHome's SPI
// abstraction (RX only), so it works on both the arduino and esp-idf
// frameworks without the RF24 library.
class NRF24BTHomeHub : public Component,
                       public spi::SPIDevice<spi::BIT_ORDER_MSB_FIRST, spi::CLOCK_POLARITY_LOW,
                                             spi::CLOCK_PHASE_LEADING, spi::DATA_RATE_4MHZ> {
 public:
  void set_ce_pin(GPIOPin *pin) { this->ce_pin_ = pin; }
  void set_channel(uint8_t channel) { this->channel_ = channel; }
  void set_address(const std::vector<uint8_t> &address);
  void set_watchdog_timeout(uint32_t timeout_ms) { this->watchdog_timeout_ = timeout_ms; }
  void register_device(NRF24BTHomeDevice *device) { this->devices_.push_back(device); }

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

 protected:
  void radio_init_();
  uint8_t read_register_(uint8_t reg);
  void write_register_(uint8_t reg, uint8_t value);
  void write_register_(uint8_t reg, const uint8_t *data, size_t len);
  void command_(uint8_t cmd);
  uint8_t read_payload_width_();
  void read_payload_(uint8_t *data, uint8_t len);
  void handle_frame_(const uint8_t *frame, uint8_t len);

  GPIOPin *ce_pin_{nullptr};
  uint8_t channel_{100};
  std::array<uint8_t, 5> address_{{'B', 'T', 'H', 'M', 'E'}};
  uint32_t watchdog_timeout_{30000};
  uint32_t last_activity_ms_{0};  // last received frame or (re-)init
  bool chip_ok_{false};
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
#endif
#ifdef USE_TEXT_SENSOR
  void set_name_text_sensor(text_sensor::TextSensor *s) { this->name_text_sensor_ = s; }
  void set_firmware_text_sensor(text_sensor::TextSensor *s) { this->firmware_text_sensor_ = s; }
#endif

 protected:
  std::array<uint8_t, 4> sender_id_{{0, 0, 0, 0}};
  int16_t last_packet_id_{-1};  // -1 = nothing received yet
  std::vector<Trigger<uint8_t, std::string> *> button_triggers_;
  std::vector<Trigger<uint8_t, int> *> dimmer_triggers_;
#ifdef USE_SENSOR
  sensor::Sensor *battery_sensor_{nullptr};
  sensor::Sensor *voltage_sensor_{nullptr};
#endif
#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *name_text_sensor_{nullptr};
  text_sensor::TextSensor *firmware_text_sensor_{nullptr};
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
