#pragma once

// The part of the radio's configuration that is arithmetic rather than SPI:
// which register bits follow from the pipes and the radio settings.
//
// Separate from nrf24.h, and deliberately free of every esphome include, for
// one reason: radio_init_() verifies its own writes by reading the registers
// back, and that check compares against the very variable it computed. A mask
// that is wrong in the first place is written wrong, read back wrong, and
// agrees with itself - the one failure the read-back cannot see. Here it can be
// checked on the host against expectations written down independently.

#include <stdint.h>
#include <stddef.h>

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

// The chip has six receive pipes; pipe 0 is reserved for the auto-ack path of a
// transmitter, so a receiver gets five.
static constexpr size_t MAX_PIPES = 5;

// A pipe as far as the register masks are concerned.
struct PipeSetup {
  uint8_t payload_size;  // 0 = dynamic payload length
  bool auto_ack;
};

// The per-pipe registers, all of which carry one bit per pipe in the same
// positions - pipe n is bit n, and the first configured pipe is pipe 1.
struct PipeMasks {
  uint8_t enabled;   // EN_RXADDR
  uint8_t auto_ack;  // EN_AA
  uint8_t dynamic;   // DYNPD
  uint8_t feature;   // FEATURE: EN_DPL, a chip-wide switch DYNPD then narrows
};

inline PipeMasks pipe_masks(const PipeSetup *pipes, size_t count) {
  PipeMasks masks{0, 0, 0, 0};
  if (pipes == nullptr) {
    return masks;
  }
  // Pipes past the fifth are dropped rather than wrapped around: a sixth pipe
  // would otherwise set bit 6 of a register that has five, and land on a
  // neighbouring field.
  const size_t used = count < MAX_PIPES ? count : MAX_PIPES;
  for (size_t i = 0; i < used; i++) {
    const uint8_t bit = static_cast<uint8_t>(1u << (i + 1));
    masks.enabled |= bit;
    if (pipes[i].auto_ack) {
      masks.auto_ack |= bit;
    }
    if (pipes[i].payload_size == 0) {
      masks.dynamic |= bit;
    }
  }
  // EN_DPL is chip-wide, so it goes on as soon as any one pipe wants dynamic
  // lengths; the pipes that do not are simply left out of DYNPD.
  masks.feature = masks.dynamic != 0 ? 0x04 : 0x00;
  return masks;
}

// RF_SETUP: the data rate lives in two bits that are not adjacent (RF_DR_LOW is
// bit 5, RF_DR_HIGH is bit 3), which is why 1 Mbps - both clear - is the value
// that comes out of setting neither.
constexpr uint8_t rf_setup_byte(DataRate rate, PALevel pa) {
  return static_cast<uint8_t>((static_cast<uint8_t>(pa) << 1) |
                              (rate == NRF24_RATE_250KBPS ? 0x20 : 0x00) |
                              (rate == NRF24_RATE_2MBPS ? 0x08 : 0x00));
}

}  // namespace nrf24
}  // namespace esphome
