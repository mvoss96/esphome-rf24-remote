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
  snprintf(this->sender_id_text_, sizeof(this->sender_id_text_), "%02X:%02X:%02X:%02X",
           this->sender_id_[0], this->sender_id_[1], this->sender_id_[2], this->sender_id_[3]);
}

bool NRF24BTHomeDevice::matches(const uint8_t *id) const {
  return memcmp(this->sender_id_.data(), id, this->sender_id_.size()) == 0;
}

void NRF24BTHomeDevice::publish_static_info() {
#ifdef USE_TEXT_SENSOR
  if (this->sender_id_text_sensor_ != nullptr) {
    this->sender_id_text_sensor_->publish_state(this->sender_id_text_);
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
    ESP_LOGW(TAG, "%s: invalid BTHome service data", this->sender_id_text_);
    return false;
  }
  if (decoder.encrypted()) {
    ESP_LOGW(TAG, "%s: encrypted BTHome payload not supported", this->sender_id_text_);
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

  // Read the whole payload first, act afterwards - see Pending in the header for
  // why nothing may be published or triggered from inside this loop.
  Pending pending;

  BTHome::Decoded obj;
  while (decoder.next(obj)) {
    switch (obj.kind) {
      case BTHome::ObjectKind::PacketId: {
        pending.packet_id = static_cast<int16_t>(obj.raw);
        break;
      }
      case BTHome::ObjectKind::ButtonEvent: {
        if (pending.button_count < MAX_EVENTS) {
          pending.buttons[pending.button_count++] = obj.event();
        } else {
          pending.overflow = true;
        }
        break;
      }
      case BTHome::ObjectKind::DimmerEvent: {
        if (pending.dimmer_count < MAX_EVENTS) {
          pending.dimmer_events[pending.dimmer_count] = obj.event();
          pending.dimmer_steps[pending.dimmer_count] = obj.steps();
          pending.dimmer_count++;
        } else {
          pending.overflow = true;
        }
        break;
      }
      case BTHome::ObjectKind::Sensor: {
        ESP_LOGV(TAG, "%s: sensor 0x%02X: %.3f", this->sender_id_text_, obj.object_id, obj.value);
        if (obj.is(BTHome::ObjectId::Battery)) {
          pending.has_battery = true;
          pending.battery = obj.value;
        }
        if (obj.is(BTHome::ObjectId::Voltage)) {
          pending.has_voltage = true;
          pending.voltage = obj.value;
        }
        break;
      }
      case BTHome::ObjectKind::Text: {
        pending.name = obj.bytes;
        pending.name_len = obj.length;
        break;
      }
      case BTHome::ObjectKind::DeviceTypeId: {
        ESP_LOGV(TAG, "%s: device type %u", this->sender_id_text_,
                 static_cast<unsigned>(obj.raw));
        break;
      }
      case BTHome::ObjectKind::FirmwareVersion: {
        pending.has_firmware = true;
        // 0xF2 is uint24 [major.minor.patch]; 0xF1 is uint32 with the major
        // byte in bits 24-31 and a trailing build byte [major.minor.patch.build].
        pending.firmware_u32 = obj.is(BTHome::ObjectId::FirmwareVersionU32);
        pending.firmware = obj.raw;
        break;
      }
      default:
        break;
    }
  }

  const auto decode_status = decoder.status();
  if (decode_status != BTHome::DecodeStatus::End) {
    // Deliberately without recording the packet id: a corrupted copy of a frame
    // must not dedup away the intact repeats that follow it. The sender sends
    // each event three times, so dropping one copy costs nothing while
    // remembering its id would cost the whole event.
    ESP_LOGW(TAG, "%s: malformed BTHome payload, discarded (%s)", this->sender_id_text_,
             decode_status == BTHome::DecodeStatus::Truncated   ? "truncated"
             : decode_status == BTHome::DecodeStatus::UnknownId ? "unknown object id"
                                                                : "error");
    return false;
  }
  if (pending.overflow) {
    ESP_LOGW(TAG, "%s: more than %u event objects in one payload, discarded",
             this->sender_id_text_, static_cast<unsigned>(MAX_EVENTS));
    return false;
  }

  // The sender repeats every frame a few times (NO_ACK broadcast); an unchanged
  // packet id identifies those repeats. Checked here rather than where the
  // object appeared, so the order of the objects cannot decide the outcome.
  if (pending.packet_id >= 0) {
    if (pending.packet_id == this->last_packet_id_) {
      return false;
    }
    this->last_packet_id_ = pending.packet_id;
  }

  this->commit_(pending);
  return true;
}

void NRF24BTHomeDevice::commit_(const Pending &pending) {
  for (uint8_t i = 0; i < pending.button_count; i++) {
    if (pending.buttons[i] == static_cast<uint8_t>(BTHome::ButtonEventType::None)) {
      continue;
    }
    const std::string name = button_event_name(pending.buttons[i]);
    ESP_LOGD(TAG, "%s: button %u: %s", this->sender_id_text_, static_cast<unsigned>(i + 1),
             name.c_str());
    for (auto *trigger : this->button_triggers_) {
      trigger->trigger(i + 1, name);
    }
  }

  for (uint8_t i = 0; i < pending.dimmer_count; i++) {
    const uint8_t event = pending.dimmer_events[i];
    if (event == static_cast<uint8_t>(BTHome::DimmerEventType::None)) {
      continue;
    }
    const bool left = event == static_cast<uint8_t>(BTHome::DimmerEventType::RotateLeft);
    const int steps = left ? -static_cast<int>(pending.dimmer_steps[i])
                           : static_cast<int>(pending.dimmer_steps[i]);
    ESP_LOGD(TAG, "%s: dimmer %u: %d steps", this->sender_id_text_,
             static_cast<unsigned>(i + 1), steps);
    for (auto *trigger : this->dimmer_triggers_) {
      trigger->trigger(i + 1, steps);
    }
  }

#ifdef USE_SENSOR
  if (pending.has_battery && this->battery_sensor_ != nullptr) {
    this->battery_sensor_->publish_state(pending.battery);
  }
  if (pending.has_voltage && this->voltage_sensor_ != nullptr) {
    this->voltage_sensor_->publish_state(pending.voltage);
  }
#endif

#ifdef USE_TEXT_SENSOR
  if (pending.name != nullptr && this->name_text_sensor_ != nullptr) {
    const std::string name(reinterpret_cast<const char *>(pending.name), pending.name_len);
    if (!this->name_text_sensor_->has_state() || this->name_text_sensor_->state != name) {
      this->name_text_sensor_->publish_state(name);
    }
  }
  if (pending.has_firmware && this->firmware_text_sensor_ != nullptr) {
    char version[16];
    if (pending.firmware_u32) {
      snprintf(version, sizeof(version), "%u.%u.%u.%u",
               static_cast<unsigned>((pending.firmware >> 24) & 0xFF),
               static_cast<unsigned>((pending.firmware >> 16) & 0xFF),
               static_cast<unsigned>((pending.firmware >> 8) & 0xFF),
               static_cast<unsigned>(pending.firmware & 0xFF));
    } else {
      snprintf(version, sizeof(version), "%u.%u.%u",
               static_cast<unsigned>((pending.firmware >> 16) & 0xFF),
               static_cast<unsigned>((pending.firmware >> 8) & 0xFF),
               static_cast<unsigned>(pending.firmware & 0xFF));
    }
    if (!this->firmware_text_sensor_->has_state() ||
        this->firmware_text_sensor_->state != version) {
      this->firmware_text_sensor_->publish_state(version);
    }
  }
#endif

#if defined(USE_SENSOR) && defined(USE_TIME)
  // Once per unique packet: repeats and discarded payloads return before this.
  if (this->last_seen_sensor_ != nullptr && this->rtc_ != nullptr) {
    const auto now = this->rtc_->utcnow();
    if (now.is_valid()) {
      this->last_seen_sensor_->publish_state(now.timestamp);
    }
  }
#endif
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
    ESP_LOGW(TAG, "%s: offline (no contact for %u ms)", this->sender_id_text_,
             static_cast<unsigned>(now_ms - reference));
    this->connected_sensor_->publish_state(false);
  }
#endif
}

void NRF24BTHomeHub::dump_config() {
  ESP_LOGCONFIG(TAG, "nRF24 BTHome receiver:");
  for (auto *dev : this->devices_) {
    ESP_LOGCONFIG(TAG, "  Device: %s", dev->sender_id_text());
  }
}

}  // namespace nrf24_bthome
}  // namespace esphome
