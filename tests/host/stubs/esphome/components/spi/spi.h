#pragma once

// Only what nrf24.h needs to be a valid declaration. The harness never drives
// the radio - it hands frames straight to the BTHome listener - so nothing here
// pretends to talk to a chip. The register logic that could be checked without
// one lives in components/nrf24/nrf24_config.h and has its own test.

#include <cstdint>

namespace esphome {
namespace spi {

enum SPIBitOrder { BIT_ORDER_LSB_FIRST, BIT_ORDER_MSB_FIRST };
enum SPIClockPolarity { CLOCK_POLARITY_LOW, CLOCK_POLARITY_HIGH };
enum SPIClockPhase { CLOCK_PHASE_LEADING, CLOCK_PHASE_TRAILING };
enum SPIDataRate {
  DATA_RATE_1KHZ,
  DATA_RATE_1MHZ,
  DATA_RATE_2MHZ,
  DATA_RATE_4MHZ,
  DATA_RATE_8MHZ,
};

template<SPIBitOrder BIT_ORDER, SPIClockPolarity CLOCK_POLARITY, SPIClockPhase CLOCK_PHASE,
         SPIDataRate DATA_RATE>
class SPIDevice {
 public:
  void spi_setup() {}

 protected:
  void enable() {}
  void disable() {}
  uint8_t transfer_byte(uint8_t data) {
    (void) data;
    return 0;
  }
  void write_byte(uint8_t data) { (void) data; }
};

}  // namespace spi
}  // namespace esphome
