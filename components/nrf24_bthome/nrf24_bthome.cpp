#include "nrf24_bthome.h"
#include "esphome/core/log.h"

#include "bthome_decode.h"

namespace esphome {
namespace nrf24_bthome {

static const char *const TAG = "nrf24_bthome";

void NRF24BTHomeHub::setup() {
  this->parent_->register_listener(this);
  for (auto *dev : this->devices_) {
    dev->publish_static_info();
  }
}

void NRF24BTHomeHub::loop() {
  // Offline detection: sweep the devices about once a second.
  if (millis() - this->last_timeout_check_ms_ > 1000) {
    this->last_timeout_check_ms_ = millis();
    for (auto *dev : this->devices_) {
      dev->check_timeout(millis());
    }
  }
}

void NRF24BTHomeHub::on_nrf24_frame(uint8_t /*pipe*/, const uint8_t *frame, uint8_t len,
                                    bool padded) {
  // [4-byte sender ID][uuid lo][uuid hi][device info][objects...]
  if (len < 4 + 3) {
    ESP_LOGV(TAG, "Frame too short (%u bytes)", len);
    return;
  }

  // A fixed-size pipe hands out the configured length whatever the sender meant,
  // so senders fill the rest with 0xFF - an object id BTHome does not define,
  // which makes it unambiguous where the data ends. Cutting it here rather than
  // in the decoder keeps the transport's padding out of the format: what BTHome
  // sees is what it would see over BLE. Only on padded pipes - on a dynamic one
  // the length is the sender's own and a trailing 0xFF is data.
  if (padded) {
    while (len > 4 + 3 && frame[len - 1] == 0xFF) {
      len--;
    }
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
        // 0xF2 is uint24 [major.minor.patch]; 0xF1 is uint32 with the major
        // byte in bits 24-31 and a trailing build byte [major.minor.patch.build].
        const bool u32 = obj.is(BTHome::ObjectId::FirmwareVersionU32);
        if (u32) {
          ESP_LOGV(TAG, "Firmware: %u.%u.%u.%u", static_cast<unsigned>((obj.raw >> 24) & 0xFF),
                   static_cast<unsigned>((obj.raw >> 16) & 0xFF),
                   static_cast<unsigned>((obj.raw >> 8) & 0xFF), static_cast<unsigned>(obj.raw & 0xFF));
        } else {
          ESP_LOGV(TAG, "Firmware: %u.%u.%u", static_cast<unsigned>((obj.raw >> 16) & 0xFF),
                   static_cast<unsigned>((obj.raw >> 8) & 0xFF), static_cast<unsigned>(obj.raw & 0xFF));
        }
#ifdef USE_TEXT_SENSOR
        if (this->firmware_text_sensor_ != nullptr) {
          char version[16];
          if (u32) {
            snprintf(version, sizeof(version), "%u.%u.%u.%u",
                     static_cast<unsigned>((obj.raw >> 24) & 0xFF),
                     static_cast<unsigned>((obj.raw >> 16) & 0xFF),
                     static_cast<unsigned>((obj.raw >> 8) & 0xFF),
                     static_cast<unsigned>(obj.raw & 0xFF));
          } else {
            snprintf(version, sizeof(version), "%u.%u.%u",
                     static_cast<unsigned>((obj.raw >> 16) & 0xFF),
                     static_cast<unsigned>((obj.raw >> 8) & 0xFF),
                     static_cast<unsigned>(obj.raw & 0xFF));
          }
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
  if (this->timeout_ms_ == 0) {
    return;
  }
  // Before the first frame the boot counts as the reference point.
  const uint32_t reference = this->ever_seen_ ? this->last_contact_ms_ : 0;
  if (now_ms - reference <= this->timeout_ms_) {
    return;
  }
  // Quiet period elapsed: forget the dedup id. The repeats it suppresses
  // arrive within milliseconds, and a sender that reboots (battery swap)
  // restarts its packet id counter - without aging, a 1-in-256 collision
  // with the stale id would swallow the sender's first frame.
  this->last_packet_id_ = -1;
#ifdef USE_BINARY_SENSOR
  if (this->connected_sensor_ != nullptr &&
      (!this->connected_sensor_->has_state() || this->connected_sensor_->state)) {
    ESP_LOGW(TAG, "Remote %02X:%02X:%02X:%02X offline (no contact for %u ms)",
             this->sender_id_[0], this->sender_id_[1], this->sender_id_[2], this->sender_id_[3],
             static_cast<unsigned>(now_ms - reference));
    this->connected_sensor_->publish_state(false);
  }
#endif
}

void NRF24BTHomeHub::dump_config() {
  ESP_LOGCONFIG(TAG, "nRF24 BTHome receiver:");
  for (auto *dev : this->devices_) {
    ESP_LOGCONFIG(TAG, "  Device: %02X:%02X:%02X:%02X", dev->sender_id()[0], dev->sender_id()[1],
                  dev->sender_id()[2], dev->sender_id()[3]);
  }
}

}  // namespace nrf24_bthome
}  // namespace esphome
