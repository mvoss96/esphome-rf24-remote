#include "nrf24_bthome.h"
#include "esphome/core/log.h"

#include "bthome_decode.h"

namespace esphome {
namespace nrf24_bthome {

static const char *const TAG = "nrf24_bthome";

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
static const uint8_t REG_FIFO_STATUS = 0x17;
static const uint8_t REG_DYNPD = 0x1C;
static const uint8_t REG_FEATURE = 0x1D;

// Register values
static const uint8_t CONFIG_STANDBY = 0x0C;  // EN_CRC | CRCO (16-bit CRC), powered down
static const uint8_t CONFIG_RX = 0x0F;       // + PWR_UP | PRIM_RX
static const uint8_t RF_SETUP_250K = 0x26;   // 250 kbps, 0 dBm
static const uint8_t STATUS_CLEAR = 0x70;    // clear RX_DR | TX_DS | MAX_RT
static const uint8_t STATUS_RX_DR = 0x40;
static const uint8_t FIFO_RX_EMPTY = 0x01;

void NRF24BTHomeHub::set_address(const std::vector<uint8_t> &address) {
  for (size_t i = 0; i < this->address_.size() && i < address.size(); i++) {
    this->address_[i] = address[i];
  }
}

void NRF24BTHomeHub::setup() {
  this->spi_setup();
  this->ce_pin_->setup();
  this->ce_pin_->digital_write(false);
  this->radio_init_();
  if (!this->chip_ok_) {
    ESP_LOGE(TAG, "nRF24 not responding - check wiring (CE/CSN/SPI)");
    this->status_set_error();
  }
  for (auto *dev : this->devices_) {
    dev->publish_static_info();
  }
}

void NRF24BTHomeHub::radio_init_() {
  this->ce_pin_->digital_write(false);
  delay(5);  // power-on / settling

  this->write_register_(REG_CONFIG, CONFIG_STANDBY);
  // ENAA_P1 must stay set: the datasheet gates dynamic payload length on
  // auto-ack being enabled for the pipe. No ACKs are transmitted anyway -
  // the senders flag every frame NO_ACK.
  this->write_register_(REG_EN_AA, 0x02);
  this->write_register_(REG_EN_RXADDR, 0x02);   // pipe 1 only
  this->write_register_(REG_SETUP_AW, 0x03);    // 5-byte addresses
  this->write_register_(REG_SETUP_RETR, 0x00);  // no auto-retransmit (RX only)
  this->write_register_(REG_RF_CH, this->channel_);
  this->write_register_(REG_RF_SETUP, RF_SETUP_250K);
  this->write_register_(REG_RX_ADDR_P1, this->address_.data(), this->address_.size());

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
  this->write_register_(REG_DYNPD, 0x02);  // dynamic payloads on pipe 1

  this->write_register_(REG_STATUS, STATUS_CLEAR);
  this->command_(CMD_FLUSH_RX);
  this->command_(CMD_FLUSH_TX);

  // Chip detection: both registers must read back what was just written.
  this->chip_ok_ = (this->read_register_(REG_SETUP_AW) == 0x03) &&
                   (this->read_register_(REG_RF_CH) == this->channel_);

  this->write_register_(REG_CONFIG, CONFIG_RX);
  delay(5);  // Tpd2stby
  this->ce_pin_->digital_write(true);  // enter RX mode

  this->last_activity_ms_ = millis();
  ESP_LOGD(TAG, "Radio initialized (chip %s)", this->chip_ok_ ? "ok" : "MISSING");

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

void NRF24BTHomeHub::loop() {
  // Drain the 3-deep RX FIFO; the guard keeps a flooded channel from
  // starving the rest of the loop.
  for (uint8_t guard = 0; guard < 8; guard++) {
    if (this->read_register_(REG_FIFO_STATUS) & FIFO_RX_EMPTY) {
      break;
    }
    const uint8_t len = this->read_payload_width_();
    if (len == 0 || len > 32) {
      // Datasheet: a corrupt width mandates flushing the RX FIFO.
      this->command_(CMD_FLUSH_RX);
      break;
    }
    uint8_t frame[32];
    this->read_payload_(frame, len);
    this->write_register_(REG_STATUS, STATUS_RX_DR);
    this->last_activity_ms_ = millis();
    this->handle_frame_(frame, len);
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

  // Offline detection: sweep the devices about once a second.
  if (millis() - this->last_timeout_check_ms_ > 1000) {
    this->last_timeout_check_ms_ = millis();
    for (auto *dev : this->devices_) {
      dev->check_timeout(millis());
    }
  }

  // The nRF24 can wedge silently (a known quirk, especially on clones):
  // re-init after a configurable quiet period.
  if (this->watchdog_timeout_ > 0 && millis() - this->last_activity_ms_ > this->watchdog_timeout_) {
    ESP_LOGV(TAG, "Watchdog: re-initializing radio");
    this->radio_init_();
    if (!this->chip_ok_) {
      this->status_set_error();
    } else {
      this->status_clear_error();
    }
  }
}

void NRF24BTHomeHub::handle_frame_(const uint8_t *frame, uint8_t len) {
  // [4-byte sender ID][uuid lo][uuid hi][device info][objects...]
  if (len < 4 + 3) {
    ESP_LOGV(TAG, "Frame too short (%u bytes)", len);
    return;
  }

  ESP_LOGVV(TAG, "Frame from %02X:%02X:%02X:%02X, %u bytes", frame[0], frame[1], frame[2],
            frame[3], len);

  NRF24BTHomeDevice *device = nullptr;
  for (auto *dev : this->devices_) {
    if (dev->matches(frame)) {
      device = dev;
      break;
    }
  }
  if (device == nullptr) {
    ESP_LOGD(TAG, "Frame from unregistered sender %02X:%02X:%02X:%02X (%u bytes)", frame[0],
             frame[1], frame[2], frame[3], len);
    return;
  }

  device->handle_service_data(frame + 4, len - 4);
}

// ---- Device -------------------------------------------------------------------

void NRF24BTHomeDevice::set_sender_id(const std::vector<uint8_t> &id) {
  for (size_t i = 0; i < this->sender_id_.size() && i < id.size(); i++) {
    this->sender_id_[i] = id[i];
  }
}

bool NRF24BTHomeDevice::matches(const uint8_t *id) const {
  return memcmp(this->sender_id_.data(), id, this->sender_id_.size()) == 0;
}

void NRF24BTHomeDevice::publish_static_info() {
#ifdef USE_TEXT_SENSOR
  if (this->sender_id_text_sensor_ != nullptr) {
    char id[12];
    snprintf(id, sizeof(id), "%02X:%02X:%02X:%02X", this->sender_id_[0], this->sender_id_[1],
             this->sender_id_[2], this->sender_id_[3]);
    this->sender_id_text_sensor_->publish_state(id);
  }
#endif
}

static std::string button_event_name(uint8_t code) {
  switch (static_cast<BTHome::ButtonEventType>(code)) {
    case BTHome::ButtonEventType::Press:
      return "press";
    case BTHome::ButtonEventType::DoublePress:
      return "double_press";
    case BTHome::ButtonEventType::TriplePress:
      return "triple_press";
    case BTHome::ButtonEventType::LongPress:
      return "long_press";
    case BTHome::ButtonEventType::LongDoublePress:
      return "long_double_press";
    case BTHome::ButtonEventType::LongTriplePress:
      return "long_triple_press";
    case BTHome::ButtonEventType::HoldPress:
      return "hold_press";
    default:
      return "unknown";
  }
}

bool NRF24BTHomeDevice::handle_service_data(const uint8_t *data, size_t len) {
  BTHome::Decoder decoder(data, len);
  if (decoder.status() == BTHome::DecodeStatus::BadHeader) {
    ESP_LOGW(TAG, "Invalid BTHome service data from %02X:%02X:%02X:%02X", this->sender_id_[0],
             this->sender_id_[1], this->sender_id_[2], this->sender_id_[3]);
    return false;
  }
  if (decoder.encrypted()) {
    ESP_LOGW(TAG, "Encrypted BTHome payload not supported");
    return false;
  }

  // Every valid frame counts as contact, including the broadcast repeats.
  this->last_contact_ms_ = millis();
  this->ever_seen_ = true;
#ifdef USE_BINARY_SENSOR
  if (this->connected_sensor_ != nullptr &&
      (!this->connected_sensor_->has_state() || !this->connected_sensor_->state)) {
    this->connected_sensor_->publish_state(true);
  }
#endif

  // Instance counters: the k-th button/dimmer object addresses instance k.
  uint8_t button_index = 0;
  uint8_t dimmer_index = 0;

  BTHome::Decoded obj;
  while (decoder.next(obj)) {
    switch (obj.kind) {
      case BTHome::ObjectKind::PacketId: {
        // The sender repeats every frame a few times (NO_ACK broadcast);
        // an unchanged packet id identifies those repeats.
        if (static_cast<int16_t>(obj.raw) == this->last_packet_id_) {
          return false;
        }
        this->last_packet_id_ = static_cast<int16_t>(obj.raw);
        break;
      }
      case BTHome::ObjectKind::ButtonEvent: {
        button_index++;
        if (obj.event() != static_cast<uint8_t>(BTHome::ButtonEventType::None)) {
          const std::string name = button_event_name(obj.event());
          ESP_LOGD(TAG, "Button %u: %s", button_index, name.c_str());
          for (auto *trigger : this->button_triggers_) {
            trigger->trigger(button_index, name);
          }
        }
        break;
      }
      case BTHome::ObjectKind::DimmerEvent: {
        dimmer_index++;
        if (obj.event() != static_cast<uint8_t>(BTHome::DimmerEventType::None)) {
          const bool left = obj.event() == static_cast<uint8_t>(BTHome::DimmerEventType::RotateLeft);
          const int steps = left ? -static_cast<int>(obj.steps()) : static_cast<int>(obj.steps());
          ESP_LOGD(TAG, "Dimmer %u: %d steps", dimmer_index, steps);
          for (auto *trigger : this->dimmer_triggers_) {
            trigger->trigger(dimmer_index, steps);
          }
        }
        break;
      }
      case BTHome::ObjectKind::Sensor: {
        ESP_LOGV(TAG, "Sensor 0x%02X: %.3f", obj.object_id, obj.value);
#ifdef USE_SENSOR
        if (obj.is(BTHome::ObjectId::Battery) && this->battery_sensor_ != nullptr) {
          this->battery_sensor_->publish_state(obj.value);
        }
        if (obj.is(BTHome::ObjectId::Voltage) && this->voltage_sensor_ != nullptr) {
          this->voltage_sensor_->publish_state(obj.value);
        }
#endif
        break;
      }
      case BTHome::ObjectKind::Text: {
        ESP_LOGV(TAG, "Device name: %.*s", obj.length, reinterpret_cast<const char *>(obj.bytes));
#ifdef USE_TEXT_SENSOR
        if (this->name_text_sensor_ != nullptr) {
          const std::string name(reinterpret_cast<const char *>(obj.bytes), obj.length);
          if (!this->name_text_sensor_->has_state() || this->name_text_sensor_->state != name) {
            this->name_text_sensor_->publish_state(name);
          }
        }
#endif
        break;
      }
      case BTHome::ObjectKind::DeviceTypeId: {
        ESP_LOGV(TAG, "Device type: %u", static_cast<unsigned>(obj.raw));
        break;
      }
      case BTHome::ObjectKind::FirmwareVersion: {
        ESP_LOGV(TAG, "Firmware: %u.%u.%u", static_cast<unsigned>((obj.raw >> 16) & 0xFF),
                 static_cast<unsigned>((obj.raw >> 8) & 0xFF), static_cast<unsigned>(obj.raw & 0xFF));
#ifdef USE_TEXT_SENSOR
        if (this->firmware_text_sensor_ != nullptr) {
          char version[16];
          snprintf(version, sizeof(version), "%u.%u.%u", static_cast<unsigned>((obj.raw >> 16) & 0xFF),
                   static_cast<unsigned>((obj.raw >> 8) & 0xFF), static_cast<unsigned>(obj.raw & 0xFF));
          if (!this->firmware_text_sensor_->has_state() ||
              this->firmware_text_sensor_->state != version) {
            this->firmware_text_sensor_->publish_state(version);
          }
        }
#endif
        break;
      }
      default:
        break;
    }
  }
  const auto decode_status = decoder.status();
  if (decode_status != BTHome::DecodeStatus::End) {
    ESP_LOGW(TAG, "Malformed BTHome payload, parsed partially (%s)",
             decode_status == BTHome::DecodeStatus::Truncated   ? "truncated"
             : decode_status == BTHome::DecodeStatus::UnknownId ? "unknown object id"
                                                                : "error");
  }

#if defined(USE_SENSOR) && defined(USE_TIME)
  // Once per unique packet (repeats returned above via the dedup).
  if (this->last_seen_sensor_ != nullptr && this->rtc_ != nullptr) {
    const auto now = this->rtc_->utcnow();
    if (now.is_valid()) {
      this->last_seen_sensor_->publish_state(now.timestamp);
    }
  }
#endif
  return true;
}

void NRF24BTHomeDevice::check_timeout(uint32_t now_ms) {
#ifdef USE_BINARY_SENSOR
  if (this->timeout_ms_ == 0 || this->connected_sensor_ == nullptr) {
    return;
  }
  // Before the first frame the boot counts as the reference point.
  const uint32_t reference = this->ever_seen_ ? this->last_contact_ms_ : 0;
  if (now_ms - reference > this->timeout_ms_) {
    if (!this->connected_sensor_->has_state() || this->connected_sensor_->state) {
      ESP_LOGW(TAG, "Remote %02X:%02X:%02X:%02X offline (no contact for %u ms)",
               this->sender_id_[0], this->sender_id_[1], this->sender_id_[2], this->sender_id_[3],
               static_cast<unsigned>(now_ms - reference));
      this->connected_sensor_->publish_state(false);
    }
  }
#endif
}

// ---- SPI plumbing ---------------------------------------------------------------

uint8_t NRF24BTHomeHub::read_register_(uint8_t reg) {
  this->enable();
  this->transfer_byte(CMD_R_REGISTER | reg);
  const uint8_t value = this->transfer_byte(0xFF);
  this->disable();
  return value;
}

void NRF24BTHomeHub::write_register_(uint8_t reg, uint8_t value) {
  this->enable();
  this->transfer_byte(CMD_W_REGISTER | reg);
  this->transfer_byte(value);
  this->disable();
}

void NRF24BTHomeHub::write_register_(uint8_t reg, const uint8_t *data, size_t len) {
  this->enable();
  this->transfer_byte(CMD_W_REGISTER | reg);
  for (size_t i = 0; i < len; i++) {
    this->transfer_byte(data[i]);
  }
  this->disable();
}

void NRF24BTHomeHub::command_(uint8_t cmd) {
  this->enable();
  this->transfer_byte(cmd);
  this->disable();
}

uint8_t NRF24BTHomeHub::read_payload_width_() {
  this->enable();
  this->transfer_byte(CMD_R_RX_PL_WID);
  const uint8_t width = this->transfer_byte(0xFF);
  this->disable();
  return width;
}

void NRF24BTHomeHub::read_payload_(uint8_t *data, uint8_t len) {
  this->enable();
  this->transfer_byte(CMD_R_RX_PAYLOAD);
  for (uint8_t i = 0; i < len; i++) {
    data[i] = this->transfer_byte(0xFF);
  }
  this->disable();
}

void NRF24BTHomeHub::dump_config() {
  ESP_LOGCONFIG(TAG, "nRF24 BTHome receiver:");
  LOG_PIN("  CE Pin: ", this->ce_pin_);
  ESP_LOGCONFIG(TAG, "  Channel: %u", this->channel_);
  ESP_LOGCONFIG(TAG, "  Address: %02X:%02X:%02X:%02X:%02X", this->address_[0], this->address_[1],
                this->address_[2], this->address_[3], this->address_[4]);
  ESP_LOGCONFIG(TAG, "  Watchdog: %u ms", this->watchdog_timeout_);
  ESP_LOGCONFIG(TAG, "  Chip connected: %s", YESNO(this->chip_ok_));
  for (auto *dev : this->devices_) {
    ESP_LOGCONFIG(TAG, "  Device: %02X:%02X:%02X:%02X", dev->sender_id()[0], dev->sender_id()[1],
                  dev->sender_id()[2], dev->sender_id()[3]);
  }
}

}  // namespace nrf24_bthome
}  // namespace esphome
