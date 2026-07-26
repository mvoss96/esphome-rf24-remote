#pragma once

#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/components/spi/spi.h"

#include <array>
#include <vector>

namespace esphome {
namespace nrf24 {

enum DataRate : uint8_t {
  NRF24_RATE_250KBPS,
  NRF24_RATE_1MBPS,
  NRF24_RATE_2MBPS,
};

// Values match the RF_SETUP RF_PWR field (bits 2:1).
enum PALevel : uint8_t {
  NRF24_PA_MIN = 0,   // -18 dBm
  NRF24_PA_LOW = 1,   // -12 dBm
  NRF24_PA_HIGH = 2,  //  -6 dBm
  NRF24_PA_MAX = 3,   //   0 dBm
};

// Implemented by consumers (e.g. nrf24_bthome). Called from loop() context,
// never from an ISR, once per received frame.
class NRF24Listener {
 public:
  virtual void on_nrf24_frame(uint8_t pipe, const uint8_t *data, uint8_t len) = 0;
};

// Generic RX driver for the nRF24L01(+): register-level over ESPHome's SPI
// abstraction, so it works on both the arduino and esp-idf frameworks
// without the RF24 library. Receives on up to 5 pipes with dynamic payload
// lengths and dispatches frames to registered listeners.
class NRF24Hub : public Component,
                 public spi::SPIDevice<spi::BIT_ORDER_MSB_FIRST, spi::CLOCK_POLARITY_LOW,
                                       spi::CLOCK_PHASE_LEADING, spi::DATA_RATE_4MHZ> {
 public:
  void set_ce_pin(GPIOPin *pin) { this->ce_pin_ = pin; }
  void set_irq_pin(InternalGPIOPin *pin) { this->irq_pin_ = pin; }
  void set_channel(uint8_t channel) { this->channel_ = channel; }
  void set_data_rate(DataRate rate) { this->data_rate_ = rate; }
  void set_pa_level(PALevel level) { this->pa_level_ = level; }
  void set_watchdog_timeout(uint32_t timeout_ms) { this->watchdog_timeout_ = timeout_ms; }
  // First call defines pipe 1 (full 5-byte address); later calls define
  // pipes 2-5, which share all but their first byte (the on-air LSB) with
  // pipe 1. Enforced by config validation.
  void add_pipe(const std::vector<uint8_t> &address);
  void register_listener(NRF24Listener *listener) { this->listeners_.push_back(listener); }

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  uint8_t channel() const { return this->channel_; }
  bool chip_ok() const { return this->chip_ok_; }

 protected:
  static void IRAM_ATTR s_irq_isr(NRF24Hub *self) { self->irq_flag_ = true; }

  void radio_init_();
  uint8_t read_register_(uint8_t reg);
  void write_register_(uint8_t reg, uint8_t value);
  void write_register_(uint8_t reg, const uint8_t *data, size_t len);
  void command_(uint8_t cmd);
  uint8_t read_payload_width_();
  void read_payload_(uint8_t *data, uint8_t len);
  void drain_fifo_();

  GPIOPin *ce_pin_{nullptr};
  InternalGPIOPin *irq_pin_{nullptr};
  volatile bool irq_flag_{false};
  uint8_t channel_{100};
  DataRate data_rate_{NRF24_RATE_250KBPS};
  PALevel pa_level_{NRF24_PA_MAX};
  std::vector<std::array<uint8_t, 5>> pipes_;
  uint32_t watchdog_timeout_{300000};  // overwritten by codegen; keep in sync with the 5min schema default
  uint32_t last_activity_ms_{0};       // last received frame or (re-)init
  bool chip_ok_{false};
  std::vector<NRF24Listener *> listeners_;
};

}  // namespace nrf24
}  // namespace esphome
