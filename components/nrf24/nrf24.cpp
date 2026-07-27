#include "nrf24.h"
#include "esphome/core/log.h"

namespace esphome {
namespace nrf24 {

static const char *const TAG = "nrf24";

// nRF24L01(+) SPI commands
static const uint8_t CMD_R_REGISTER = 0x00;
static const uint8_t CMD_W_REGISTER = 0x20;
static const uint8_t CMD_R_RX_PL_WID = 0x60;
static const uint8_t CMD_R_RX_PAYLOAD = 0x61;
static const uint8_t CMD_FLUSH_TX = 0xE1;
static const uint8_t CMD_FLUSH_RX = 0xE2;
static const uint8_t CMD_ACTIVATE = 0x50;  // non-plus clones gate FEATURE behind this

// nRF24L01(+) registers
static const uint8_t REG_CONFIG = 0x00;
static const uint8_t REG_EN_AA = 0x01;
static const uint8_t REG_EN_RXADDR = 0x02;
static const uint8_t REG_SETUP_AW = 0x03;
static const uint8_t REG_SETUP_RETR = 0x04;
static const uint8_t REG_RF_CH = 0x05;
static const uint8_t REG_RF_SETUP = 0x06;
static const uint8_t REG_STATUS = 0x07;
static const uint8_t REG_RPD = 0x09;  // received power detector (carrier > ~-64 dBm)
static const uint8_t REG_RX_ADDR_P1 = 0x0B;
static const uint8_t REG_RX_ADDR_P2 = 0x0C;  // P3-P5 follow contiguously
static const uint8_t REG_RX_PW_P1 = 0x12;    // P2-P5 follow contiguously
static const uint8_t REG_FIFO_STATUS = 0x17;
static const uint8_t REG_DYNPD = 0x1C;
static const uint8_t REG_FEATURE = 0x1D;

// Register values. TX_DS/MAX_RT interrupts are always masked so a wired IRQ
// pin only fires on RX_DR; harmless without an IRQ pin.
static const uint8_t CONFIG_STANDBY = 0x3C;  // MASK_TX_DS | MASK_MAX_RT | EN_CRC | CRCO
static const uint8_t CONFIG_RX = 0x3F;       // + PWR_UP | PRIM_RX
static const uint8_t STATUS_CLEAR = 0x70;    // clear RX_DR | TX_DS | MAX_RT
static const uint8_t STATUS_RX_DR = 0x40;
static const uint8_t FIFO_RX_EMPTY = 0x01;
static const uint8_t FIFO_RX_FULL = 0x02;

void NRF24Hub::add_pipe(const std::vector<uint8_t> &address) {
  std::array<uint8_t, 5> addr{};
  for (size_t i = 0; i < addr.size() && i < address.size(); i++) {
    addr[i] = address[i];
  }
  this->pipes_.push_back(addr);
}

void NRF24Hub::setup() {
  this->spi_setup();
  this->ce_pin_->setup();
  this->ce_pin_->digital_write(false);
  if (this->irq_pin_ != nullptr) {
    this->irq_pin_->setup();
    this->irq_pin_->attach_interrupt(NRF24Hub::s_irq_isr, this, gpio::INTERRUPT_FALLING_EDGE);
  }
  this->radio_init_();
  if (!this->chip_ok_) {
    ESP_LOGE(TAG, "nRF24 not responding - check wiring (CE/CSN/SPI)");
    this->status_set_error();
  }
}

void NRF24Hub::radio_init_() {
  this->ce_pin_->digital_write(false);
  delay(5);  // power-on / settling

  // One enable bit per configured pipe: first entry is pipe 1, further
  // entries are pipes 2-5.
  uint8_t pipe_mask = 0;
  for (size_t i = 0; i < this->pipes_.size() && i < 5; i++) {
    pipe_mask |= 1 << (i + 1);
  }

  this->write_register_(REG_CONFIG, CONFIG_STANDBY);
  // Auto acknowledgement, per pipe. Configurable, but not freely: with dynamic
  // payload length the datasheet requires it (Table 28, DYNPD, page 63 - "Requires
  // EN_DPL and ENAA_Pn"), and the config schema rejects that combination before
  // it can reach the chip. Measured consequence of getting it wrong on these
  // modules: payloads shorter than 32 bytes delivered twice, the second copy
  // carrying an older payload, so one click fired three button events.
  //
  // With a fixed payload size it is a real choice, and off is the better one for
  // a broadcast network: on these modules the NO_ACK bit is inverted, so a
  // receiver with auto-ack answers even frames flagged NO_ACK - captured on the
  // air as a 1-byte frame behind the broadcast, landing on top of the traffic
  // every other receiver is trying to hear.
  this->write_register_(REG_EN_AA, this->auto_ack_ ? pipe_mask : 0x00);
  this->write_register_(REG_EN_RXADDR, pipe_mask);
  this->write_register_(REG_SETUP_AW, 0x03);    // 5-byte addresses
  this->write_register_(REG_SETUP_RETR, 0x00);  // no auto-retransmit (RX only)
  this->write_register_(REG_RF_CH, this->channel_);

  // RF_SETUP: data rate bits (RF_DR_LOW=bit5, RF_DR_HIGH=bit3) + PA (bits 2:1).
  uint8_t rf_setup = static_cast<uint8_t>(this->pa_level_) << 1;
  if (this->data_rate_ == NRF24_RATE_250KBPS) {
    rf_setup |= 0x20;
  } else if (this->data_rate_ == NRF24_RATE_2MBPS) {
    rf_setup |= 0x08;
  }
  this->write_register_(REG_RF_SETUP, rf_setup);

  if (!this->pipes_.empty()) {
    // Pipe 1 carries the full 5-byte address; pipes 2-5 only their first
    // byte (the on-air LSB) - the remaining bytes are shared with pipe 1.
    this->write_register_(REG_RX_ADDR_P1, this->pipes_[0].data(), 5);
    for (size_t i = 1; i < this->pipes_.size() && i < 5; i++) {
      this->write_register_(REG_RX_ADDR_P2 + (i - 1), this->pipes_[i][0]);
    }
  }

  if (this->payload_size_ == 0) {
    // Dynamic payload lengths; some clones need the ACTIVATE handshake before
    // FEATURE becomes writable, so verify and retry once.
    this->write_register_(REG_FEATURE, 0x04);  // EN_DPL
    if (this->read_register_(REG_FEATURE) != 0x04) {
      this->enable();
      this->transfer_byte(CMD_ACTIVATE);
      this->transfer_byte(0x73);
      this->disable();
      this->write_register_(REG_FEATURE, 0x04);
    }
    this->write_register_(REG_DYNPD, pipe_mask);
  } else {
    // Static payload length: the size lives on the receiver, in RX_PW_Pn, and
    // has to match what the sender clocks into its TX FIFO (spec section 7.3.4,
    // page 29). Nothing here asks the chip how long a payload is, which is the
    // point - it is the one length question these modules answer unreliably.
    this->write_register_(REG_FEATURE, 0x00);
    this->write_register_(REG_DYNPD, 0x00);
    for (size_t i = 0; i < this->pipes_.size() && i < 5; i++) {
      this->write_register_(REG_RX_PW_P1 + i, this->payload_size_);
    }
  }

  this->write_register_(REG_STATUS, STATUS_CLEAR);
  this->command_(CMD_FLUSH_RX);
  this->command_(CMD_FLUSH_TX);

  // Chip detection: both registers must read back what was just written.
  this->chip_ok_ = (this->read_register_(REG_SETUP_AW) == 0x03) &&
                   (this->read_register_(REG_RF_CH) == this->channel_);

  // Probed while the radio is still in standby, so nothing is in flight when the
  // register is written and put back.
  if (this->chip_ok_) {
    this->clone_suspected_ = this->rf_setup_bit0_writable_();
  }

  this->write_register_(REG_CONFIG, CONFIG_RX);
  delay(5);  // Tpd2stby
  this->ce_pin_->digital_write(true);  // enter RX mode

  this->last_activity_ms_ = millis();
  ESP_LOGD(TAG, "Radio initialized (chip %s, %s)", this->chip_ok_ ? "ok" : "MISSING",
           this->clone_suspected_ ? "Si24R1-like" : "nRF24L01+-like");

  uint8_t addr[5] = {0};
  this->enable();
  this->transfer_byte(CMD_R_REGISTER | REG_RX_ADDR_P1);
  for (uint8_t &b : addr) {
    b = this->transfer_byte(0xFF);
  }
  this->disable();
  ESP_LOGD(TAG,
           "Regs: CONFIG=%02X EN_AA=%02X EN_RXADDR=%02X AW=%02X CH=%u RF=%02X FEATURE=%02X "
           "DYNPD=%02X FIFO=%02X P1=%02X:%02X:%02X:%02X:%02X",
           this->read_register_(REG_CONFIG), this->read_register_(REG_EN_AA),
           this->read_register_(REG_EN_RXADDR), this->read_register_(REG_SETUP_AW),
           this->read_register_(REG_RF_CH), this->read_register_(REG_RF_SETUP),
           this->read_register_(REG_FEATURE), this->read_register_(REG_DYNPD),
           this->read_register_(REG_FIFO_STATUS), addr[0], addr[1], addr[2], addr[3], addr[4]);
}

// Genuine nRF24L01+ silicon has no use for bit 0 of RF_SETUP - its datasheet
// marks the bit obsolete and the chip holds it at zero. On the Si24R1, the clone
// routinely sold under the Nordic part number, that same bit is the low bit of
// its own RF_PWR field, so it can be written and read back. Writing it is
// therefore the one cheap way to tell the two apart without a microscope or a
// current meter.
//
// Why care: the Si24R1 hands out every payload shorter than 32 bytes twice, the
// second copy carrying an earlier payload. A stale copy whose packet id differs
// from the current one passes a packet-id filter and arrives at a listener as a
// button press nobody made.
//
// The test comes from a proposal in the RF24 library's issue tracker
// (nRF24/RF24#603) and has not been confirmed against a known-genuine part, so
// it is reported as a suspicion and nothing depends on it.
bool NRF24Hub::rf_setup_bit0_writable_() {
  const uint8_t saved = this->read_register_(REG_RF_SETUP);
  this->write_register_(REG_RF_SETUP, static_cast<uint8_t>(saved | 0x01));
  const bool stuck = (this->read_register_(REG_RF_SETUP) & 0x01) != 0;
  this->write_register_(REG_RF_SETUP, saved);
  return stuck;
}

void NRF24Hub::drain_fifo_() {
  // Drain the 3-deep RX FIFO; the guard keeps a flooded channel from
  // starving the rest of the loop.
  for (uint8_t guard = 0; guard < 8; guard++) {
    const uint8_t fifo = this->read_register_(REG_FIFO_STATUS);
    if (fifo & FIFO_RX_EMPTY) {
      break;
    }
    // A full FIFO means frames arriving right now are being dropped by the
    // chip, and it has no lost-frame counter to ask afterwards - so this is the
    // only evidence there is. It says at least one frame was at risk, not that
    // exactly one was lost. Measured: copies sent back to back with no gap do
    // get lost this way, while a real sender's few-ms repeats all arrive.
    if (fifo & FIFO_RX_FULL) {
      if (this->fifo_full_count_ < 0xFFFF) {
        this->fifo_full_count_++;
      }
      ESP_LOGW(TAG, "RX FIFO full, frames may have been dropped (n=%u)",
               static_cast<unsigned>(this->fifo_full_count_));
    }
    // RX_P_NO in STATUS names the pipe of the payload at the FIFO top.
    const uint8_t pipe = (this->read_register_(REG_STATUS) >> 1) & 0x07;
    // With a fixed size the length is known and the chip is never asked.
    const uint8_t len =
        this->payload_size_ != 0 ? this->payload_size_ : this->read_payload_width_();
    if (len == 0 || len > 32) {
      // Datasheet: a corrupt width mandates flushing the RX FIFO.
      if (this->bad_length_count_ < 0xFFFF) {
        this->bad_length_count_++;
      }
      ESP_LOGW(TAG, "Chip reported a payload width of %u, flushing RX FIFO (n=%u)",
               static_cast<unsigned>(len), static_cast<unsigned>(this->bad_length_count_));
      this->command_(CMD_FLUSH_RX);
      break;
    }
    if (this->rx_frames_ < 0xFFFFFFFF) {
      this->rx_frames_++;
    }
    // "Short" means shorter than a slot: those are the ones this hardware
    // mishandles, and the ones an outage loses first. Counting them separately
    // turns "the lamp stopped reacting" into a number that can be looked at.
    if (len < 32 && this->rx_short_frames_ < 0xFFFFFFFF) {
      this->rx_short_frames_++;
    }
    uint8_t frame[32];
    this->read_payload_(frame, len);
    this->write_register_(REG_STATUS, STATUS_RX_DR);
    this->last_activity_ms_ = millis();

#if ESPHOME_LOG_LEVEL >= ESPHOME_LOG_LEVEL_VERBOSE
    // The frame as it came out of the FIFO, before any listener interprets it.
    // Two receivers can then be compared byte for byte against what the sender
    // logged - which is how you tell a real transmission from corruption on one
    // receiver's own path, and the only way to be sure that an unexpected
    // packet id was on the air rather than a flipped bit. Compiled out below
    // VERBOSE, so production builds pay nothing.
    static const char DIGITS[] = "0123456789ABCDEF";
    char hex[65];
    for (uint8_t i = 0; i < len; i++) {
      hex[i * 2] = DIGITS[frame[i] >> 4];
      hex[i * 2 + 1] = DIGITS[frame[i] & 0x0F];
    }
    hex[len * 2] = '\0';
    ESP_LOGV(TAG, "RX p%u len=%u %s", static_cast<unsigned>(pipe),
             static_cast<unsigned>(len), hex);
#endif

    for (auto *listener : this->listeners_) {
      listener->on_nrf24_frame(pipe, frame, len);
    }
  }
}

void NRF24Hub::loop() {
  if (this->irq_pin_ == nullptr) {
    this->drain_fifo_();
  } else if (this->irq_flag_) {
    // Clear before draining: a frame arriving mid-drain re-arms the flag.
    this->irq_flag_ = false;
    this->drain_fifo_();
  }

#if ESPHOME_LOG_LEVEL >= ESPHOME_LOG_LEVEL_VERBOSE
  // Diagnostic: sample the carrier detector so RF-level problems can be
  // told apart from protocol-level ones. Compiled out below VERBOSE so
  // production builds don't pay an extra SPI read per loop.
  if (this->read_register_(REG_RPD) & 0x01) {
    static uint32_t last_rpd_log = 0;
    if (millis() - last_rpd_log > 1000) {
      last_rpd_log = millis();
      ESP_LOGV(TAG, "RF energy on channel %u", this->channel_);
    }
  }
#endif

  // The nRF24 can wedge silently (a known quirk, especially on clones):
  // re-init after a configurable quiet period. Also the safety net for a
  // missed IRQ edge when an IRQ pin is configured.
  if (this->watchdog_timeout_ > 0 && millis() - this->last_activity_ms_ > this->watchdog_timeout_) {
    if (this->watchdog_count_ < 0xFFFF) {
      this->watchdog_count_++;
    }
    // Was VERBOSE, which meant the one device that could have told us how often
    // this fires said nothing at the log level it actually runs at.
    ESP_LOGD(TAG, "Watchdog: no frame for %u ms, re-initializing radio (n=%u)",
             static_cast<unsigned>(this->watchdog_timeout_),
             static_cast<unsigned>(this->watchdog_count_));
    this->radio_init_();
    if (!this->chip_ok_) {
      this->status_set_error();
    } else {
      this->status_clear_error();
    }
  }
}

void NRF24Hub::dump_config() {
  ESP_LOGCONFIG(TAG, "nRF24:");
  LOG_PIN("  CE Pin: ", this->ce_pin_);
  if (this->irq_pin_ != nullptr) {
    LOG_PIN("  IRQ Pin: ", this->irq_pin_);
  }
  ESP_LOGCONFIG(TAG, "  Channel: %u", this->channel_);
  ESP_LOGCONFIG(TAG, "  Data rate: %s", this->data_rate_ == NRF24_RATE_250KBPS ? "250kbps"
                                        : this->data_rate_ == NRF24_RATE_1MBPS ? "1Mbps"
                                                                               : "2Mbps");
  for (size_t i = 0; i < this->pipes_.size(); i++) {
    const auto &p = this->pipes_[i];
    ESP_LOGCONFIG(TAG, "  Pipe %u: %02X:%02X:%02X:%02X:%02X", static_cast<unsigned>(i + 1), p[0],
                  p[1], p[2], p[3], p[4]);
  }
  ESP_LOGCONFIG(TAG, "  Auto ack: %s", this->auto_ack_ ? "on" : "off");
  if (this->payload_size_ == 0) {
    ESP_LOGCONFIG(TAG, "  Payload size: dynamic");
  } else {
    ESP_LOGCONFIG(TAG, "  Payload size: %u bytes (fixed)",
                  static_cast<unsigned>(this->payload_size_));
  }
  ESP_LOGCONFIG(TAG, "  Watchdog: %u ms", static_cast<unsigned>(this->watchdog_timeout_));
  ESP_LOGCONFIG(TAG, "  Chip connected: %s", this->chip_ok_ ? "YES" : "NO");
  // Printed on every dump_config, so `esphome logs` after a silent spell answers
  // "did it hear anything?" without anyone having to reproduce the fault first.
  ESP_LOGCONFIG(TAG, "  Frames: %u (%u shorter than a slot), bad length: %u, "
                     "FIFO full: %u, watchdog: %u",
                static_cast<unsigned>(this->rx_frames_),
                static_cast<unsigned>(this->rx_short_frames_),
                static_cast<unsigned>(this->bad_length_count_),
                static_cast<unsigned>(this->fifo_full_count_),
                static_cast<unsigned>(this->watchdog_count_));
  if (this->chip_ok_) {
    ESP_LOGCONFIG(TAG, "  Chip type: %s",
                  this->clone_suspected_ ? "Si24R1-like clone (RF_SETUP bit 0 is writable)"
                                         : "nRF24L01+-like (RF_SETUP bit 0 reads back as 0)");
    if (this->clone_suspected_) {
      // Worth a warning rather than a config line: on this part a short payload
      // is delivered twice, the second time with an older payload, and a stale
      // copy with a different packet id looks like a real second event.
      ESP_LOGW(TAG, "Module looks like an Si24R1 clone - expect duplicated frames "
                    "carrying stale payloads");
    }
  }
}

// ---- SPI plumbing ---------------------------------------------------------------

uint8_t NRF24Hub::read_register_(uint8_t reg) {
  this->enable();
  this->transfer_byte(CMD_R_REGISTER | reg);
  const uint8_t value = this->transfer_byte(0xFF);
  this->disable();
  return value;
}

void NRF24Hub::write_register_(uint8_t reg, uint8_t value) {
  this->enable();
  this->transfer_byte(CMD_W_REGISTER | reg);
  this->transfer_byte(value);
  this->disable();
}

void NRF24Hub::write_register_(uint8_t reg, const uint8_t *data, size_t len) {
  this->enable();
  this->transfer_byte(CMD_W_REGISTER | reg);
  for (size_t i = 0; i < len; i++) {
    this->transfer_byte(data[i]);
  }
  this->disable();
}

void NRF24Hub::command_(uint8_t cmd) {
  this->enable();
  this->transfer_byte(cmd);
  this->disable();
}

uint8_t NRF24Hub::read_payload_width_() {
  this->enable();
  this->transfer_byte(CMD_R_RX_PL_WID);
  const uint8_t width = this->transfer_byte(0xFF);
  this->disable();
  return width;
}

void NRF24Hub::read_payload_(uint8_t *data, uint8_t len) {
  this->enable();
  this->transfer_byte(CMD_R_RX_PAYLOAD);
  for (uint8_t i = 0; i < len; i++) {
    data[i] = this->transfer_byte(0xFF);
  }
  this->disable();
}

}  // namespace nrf24
}  // namespace esphome
