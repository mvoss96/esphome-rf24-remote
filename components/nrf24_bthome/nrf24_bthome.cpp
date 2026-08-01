#include "nrf24_bthome.h"
#include "esphome/core/log.h"

#include <algorithm>

#include "bthome_decode.h"
#include "object_names.h"

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
  // which makes it unambiguous where the data ends.
  //
  // Unambiguous only where an object id is expected, though. This used to trim
  // every trailing 0xFF, which also eats value bytes that happen to be 0xFF:
  // BTHome is little endian, so a signed 16-bit measurement between -0.01 and
  // -2.56 ends in 0xFF. Measured - a temperature of -1.00 C arrives as
  // "02 9C FF", loses its high byte to the trim, and the whole frame is then
  // discarded as truncated. An outdoor sensor would go silent just below
  // freezing, with nothing but a malformed-payload line to show for it.
  //
  // So the padding is not cut here at all. The decoder walks the objects, and
  // where it reports an unknown object id of 0xFF it has reached the padding
  // rather than corruption - handled at the end of handle_service_data().
  //
  // An encrypted payload cannot be walked, though, so for that one case the
  // flag has to travel down with the frame; decrypt_() explains what it does
  // with it.

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

  device->handle_service_data(frame + 4, len - 4, padded);
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

#ifdef USE_BTHOME_ENCRYPTION
void NRF24BTHomeDevice::set_encryption_key(const std::vector<uint8_t> &key) {
  uint8_t bytes[BTHome::Encryptor::kKeyBytes] = {};
  for (size_t i = 0; i < sizeof(bytes) && i < key.size(); i++) {
    bytes[i] = key[i];
  }
  this->decryptor_.setKey(bytes);
  this->encrypted_ = true;
}

void NRF24BTHomeDevice::set_nonce_mac(const std::vector<uint8_t> &mac) {
  uint8_t bytes[BTHome::Encryptor::kMacBytes] = {};
  for (size_t i = 0; i < sizeof(bytes) && i < mac.size(); i++) {
    bytes[i] = mac[i];
  }
  this->decryptor_.setMac(bytes);
}

// An encrypted payload is [uuid lo][uuid hi][device info][ciphertext][counter][MIC],
// and unlike the plaintext one it cannot be walked: where the ciphertext ends is
// where the counter begins, and both are indistinguishable from noise. That is a
// problem exactly here, because the senders this transport is built for use a
// fixed 32-byte slot and fill the tail with 0xFF - so the frame handed up is
// longer than the data in it, and counter and MIC would be read out of padding.
//
// The padding does still say where the data ends, just not quite exactly: the
// last byte that is not 0xFF is the last byte of the MIC, unless the MIC itself
// happens to end in 0xFF. So the candidates are that length and a few past it,
// and the MIC settles which one is right - it authenticates the whole payload
// and will not verify against a wrong length. That is one candidate in 255 cases
// out of 256, and a wrong one costs a decrypt the receiver would spend anyway.
//
// Trimming the padding first, the way a plaintext frame must never be trimmed,
// is safe here for the same reason it is unsafe there: this walks back from the
// end only to bound the search, and the MIC - not the trimming - decides.
NRF24BTHomeDevice::DecryptResult NRF24BTHomeDevice::decrypt_(const uint8_t *data, size_t len,
                                                             bool padded, uint8_t *out,
                                                             size_t out_capacity) {
  // [uuid lo][uuid hi][device info] plus counter and MIC: the shortest encrypted
  // payload there can be, carrying no objects at all.
  constexpr size_t MIN_LEN = 3 + BTHome::Encryptor::kOverheadBytes;
  // How many trailing 0xFF the MIC is allowed to end in before the payload is
  // given up on. Each step costs one decrypt attempt and the odds of needing it
  // fall by 256 per byte, so a whole MIC of 0xFF is covered.
  constexpr size_t MAX_TRAILING_FF = BTHome::Encryptor::kMicBytes;

  DecryptResult result;
  // Asked before the length, and for the reason the library asks it first too:
  // a plaintext payload is typically shorter than counter and MIC together, so
  // reporting it as a truncated frame would send one looking for a radio fault
  // instead of for the sender that is not encrypting.
  if (len < 3 || (data[2] & BTHome::DeviceInfo::kEncryptedBit) == 0) {
    result.status = len < 3 ? BTHome::DecryptStatus::BadBuffer
                            : BTHome::DecryptStatus::NotEncrypted;
    return result;
  }
  if (len < MIN_LEN) {
    result.status = BTHome::DecryptStatus::BadBuffer;
    return result;
  }

  size_t first = len;
  size_t last = len;
  if (padded) {
    size_t end = len;
    while (end > 0 && data[end - 1] == 0xFF) {
      end--;
    }
    first = end < MIN_LEN ? MIN_LEN : end;
    last = first + MAX_TRAILING_FF;
    if (last > len) {
      last = len;
    }
  }

  for (size_t cand = first; cand <= last; cand++) {
    // In the clear, right before the MIC, so it can be read whether or not the
    // payload authenticates - which is what tells a repeat from a sender that
    // restarted its counter.
    const uint8_t *counter_bytes = data + cand - BTHome::Encryptor::kOverheadBytes;
    const uint32_t counter = static_cast<uint32_t>(counter_bytes[0]) |
                             (static_cast<uint32_t>(counter_bytes[1]) << 8) |
                             (static_cast<uint32_t>(counter_bytes[2]) << 16) |
                             (static_cast<uint32_t>(counter_bytes[3]) << 24);
    size_t plain_len = 0;
    const auto status =
        this->decryptor_.decryptServiceData(data, cand, out, out_capacity, plain_len);
    if (status == BTHome::DecryptStatus::Ok) {
      return DecryptResult{status, plain_len, counter};
    }
    if (cand == first) {
      // The shortest candidate is the right one unless the MIC ends in 0xFF, so
      // its verdict is the one worth reporting when none of them authenticates.
      result = DecryptResult{status, 0, counter};
    }
    // Neither depends on where the payload ends, so trying further lengths
    // would only repeat the same answer.
    if (status == BTHome::DecryptStatus::NotEncrypted ||
        status == BTHome::DecryptStatus::NoBackend) {
      return result;
    }
  }
  return result;
}

void NRF24BTHomeDevice::report_decrypt_failure_(const DecryptResult &result) {
  // The ordinary case, and not a fault: the sender broadcasts every frame a few
  // times and each copy carries the counter of the first. This is the encrypted
  // transport's deduplication, and a tighter one than the packet id - the repeat
  // never reaches the decoder, and cannot be forged without the bindkey.
  if (result.status == BTHome::DecryptStatus::Replay &&
      result.counter == this->decryptor_.lastCounter()) {
    ESP_LOGV(TAG, "%s: repeat of counter %u", this->sender_id_text_,
             static_cast<unsigned>(result.counter));
    return;
  }

  if (this->warned_decrypt_ && this->warned_status_ == result.status) {
    ESP_LOGV(TAG, "%s: payload rejected again (status %u)", this->sender_id_text_,
             static_cast<unsigned>(result.status));
    return;
  }
  this->warned_decrypt_ = true;
  this->warned_status_ = result.status;

  switch (result.status) {
    case BTHome::DecryptStatus::Replay:
      // Strictly lower, so not a repeat. The senders of this ecosystem persist
      // their counter and resume above it, which is what makes this worth a
      // warning rather than a shrug: it means one that did not.
      ESP_LOGW(TAG,
               "%s: counter went backwards (%u, last accepted %u), discarded - the "
               "sender restarted without resuming its counter. Accepting it would "
               "reopen the replay window. Give the sender a counter above the last "
               "accepted one, or restart this receiver to forget it",
               this->sender_id_text_, static_cast<unsigned>(result.counter),
               static_cast<unsigned>(this->decryptor_.lastCounter()));
      break;
    case BTHome::DecryptStatus::AuthFailed:
      ESP_LOGW(TAG,
               "%s: payload did not authenticate, discarded - wrong encryption_key, "
               "or the payload was tampered with",
               this->sender_id_text_);
      break;
    case BTHome::DecryptStatus::NotEncrypted:
      // Refused rather than read: a device that accepts both encrypted and
      // plaintext payloads is not encrypted at all, because an attacker simply
      // sends the plaintext one.
      ESP_LOGW(TAG,
               "%s: plaintext payload from a sender configured with an "
               "encryption_key, discarded",
               this->sender_id_text_);
      break;
    case BTHome::DecryptStatus::BadBuffer:
      ESP_LOGW(TAG, "%s: encrypted payload too short to hold a counter and MIC",
               this->sender_id_text_);
      break;
    default:
      ESP_LOGW(TAG, "%s: encrypted payload rejected (status %u)", this->sender_id_text_,
               static_cast<unsigned>(result.status));
      break;
  }
}
#endif

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

static std::string command_event_name(uint8_t opcode) {
  switch (static_cast<BTHome::CommandEventType>(opcode)) {
    case BTHome::CommandEventType::Off:
      return "off";
    case BTHome::CommandEventType::On:
      return "on";
    case BTHome::CommandEventType::Toggle:
      return "toggle";
    case BTHome::CommandEventType::StepUp:
      return "step_up";
    case BTHome::CommandEventType::StepDown:
      return "step_down";
    default:
      return "unknown";
  }
}

bool NRF24BTHomeDevice::handle_service_data(const uint8_t *data, size_t len, bool padded) {
#ifdef USE_BTHOME_ENCRYPTION
  // Holds the plaintext for as long as the payload is being read. Everything
  // that points into the frame - the device name, the text and raw slots - is
  // read again in commit_(), which still runs inside this function, so this
  // outliving the parse is what makes those pointers safe.
  //
  // A whole frame minus the sender id is 28 bytes and the plaintext is shorter
  // still, counter and MIC having dropped out; 32 is the frame the radio hands
  // over, and sizing it that way means no arithmetic to get wrong.
  uint8_t plain[32];
  if (this->encrypted_) {
    const auto result = this->decrypt_(data, len, padded, plain, sizeof(plain));
    if (result.status != BTHome::DecryptStatus::Ok) {
      this->report_decrypt_failure_(result);
      return false;
    }
    // A fault that comes back is worth hearing about again.
    this->warned_decrypt_ = false;
    data = plain;
    len = result.plain_len;
  }
#else
  (void) padded;
#endif

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

  // Per-payload instance counters: how often each object id has been seen so
  // far. Twelve is the most a frame can carry - a 32-byte slot leaves 25 bytes
  // of objects after the sender id and the BTHome header, and the smallest
  // object is two bytes. It used to be eight, on the belief that a frame could
  // not hold more; twelve single-byte objects fit, and the ninth id onwards
  // would then have been counted as instance 1 every time.
  uint8_t seen_ids[12] = {};
  uint8_t seen_instances[12] = {};
  uint8_t seen_count = 0;
  // The k-th object of a type addresses instance k. Counted per payload and per
  // object id, so a node with two temperature probes can have one entity each
  // instead of the second silently overwriting the first. Measurements and
  // binary objects share the counter because their id spaces do not overlap.
  auto instance_of = [&](uint8_t object_id) -> uint8_t {
    for (uint8_t i = 0; i < seen_count; i++) {
      if (seen_ids[i] == object_id) {
        return ++seen_instances[i];
      }
    }
    if (seen_count < sizeof(seen_ids)) {
      seen_ids[seen_count] = object_id;
      seen_instances[seen_count] = 1;
      seen_count++;
    }
    return 1;
  };
  // An object no configured entity took. Worth saying once, because from the
  // outside it is indistinguishable from a sender that never sent it: the
  // remote broadcasts a temperature, no sensor is set up for it, and nothing
  // anywhere says the value was there for the taking. Recorded now and reported
  // in commit_(), so the sender's repeats do not say it three times over.
  auto note_unclaimed = [](Pending &p, uint8_t object_id, uint8_t instance, bool claimed) {
    if (claimed || p.unclaimed_count >= MAX_EVENTS) {
      return;
    }
    p.unclaimed[p.unclaimed_count++] =
        static_cast<uint16_t>(object_id) << 8 | static_cast<uint16_t>(instance);
  };
#ifdef USE_SENSOR
  for (auto &slot : this->object_sensors_) {
    slot.has_pending = false;
  }
#endif
#ifdef USE_BINARY_SENSOR
  for (auto &slot : this->object_binary_sensors_) {
    slot.has_pending = false;
  }
#endif
#ifdef USE_TEXT_SENSOR
  for (auto &slot : this->object_text_sensors_) {
    slot.has_pending = false;
  }
#endif

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
      case BTHome::ObjectKind::CommandEvent: {
        if (pending.command_count < MAX_EVENTS) {
          // The decoder packs [opcode][first argument] the way the dimmer
          // object's two wire bytes already land, so event() and steps() read
          // it. Commands without an argument leave steps() at zero.
          pending.command_opcodes[pending.command_count] = obj.event();
          pending.command_args[pending.command_count] = obj.steps();
          pending.command_count++;
        } else {
          pending.overflow = true;
        }
        break;
      }
      case BTHome::ObjectKind::Sensor: {
        const uint8_t instance = instance_of(obj.object_id);
        ESP_LOGV(TAG, "%s: sensor 0x%02X#%u: %.3f", this->sender_id_text_, obj.object_id,
                 instance, obj.value);
        bool claimed = false;
#ifdef USE_SENSOR
        for (auto &slot : this->object_sensors_) {
          if (slot.object_id == obj.object_id && slot.index == instance) {
            slot.has_pending = true;
            slot.pending = obj.value;
            claimed = true;
          }
        }
#endif
        note_unclaimed(pending, obj.object_id, instance, claimed);
        break;
      }
      case BTHome::ObjectKind::Binary: {
        const uint8_t instance = instance_of(obj.object_id);
        const bool state = obj.raw != 0;
        ESP_LOGV(TAG, "%s: binary 0x%02X#%u: %s", this->sender_id_text_, obj.object_id,
                 instance, state ? "on" : "off");
        bool claimed = false;
#ifdef USE_BINARY_SENSOR
        for (auto &slot : this->object_binary_sensors_) {
          if (slot.object_id == obj.object_id && slot.index == instance) {
            slot.has_pending = true;
            slot.pending = state;
            claimed = true;
          }
        }
#endif
        note_unclaimed(pending, obj.object_id, instance, claimed);
        break;
      }
      case BTHome::ObjectKind::Text:
      case BTHome::ObjectKind::Raw: {
        const bool is_text = obj.kind == BTHome::ObjectKind::Text;
        const uint8_t instance = instance_of(obj.object_id);
        ESP_LOGV(TAG, "%s: %s 0x%02X#%u: %u bytes", this->sender_id_text_,
                 is_text ? "text" : "raw", obj.object_id, instance,
                 static_cast<unsigned>(obj.length));
        // The device name is the first text object, which is what senders use
        // 0x53 for; further ones need a text_sensor of their own.
        bool claimed = false;
        if (is_text && instance == 1) {
          pending.name = obj.bytes;
          pending.name_len = obj.length;
          // Taken whether or not a name text sensor exists: it also feeds the
          // device-name log line, so it is never an object nobody looked at.
          claimed = true;
        }
#ifdef USE_TEXT_SENSOR
        for (auto &slot : this->object_text_sensors_) {
          if (slot.object_id == obj.object_id && slot.index == instance) {
            slot.has_pending = true;
            slot.bytes = obj.bytes;
            slot.length = obj.length;
            claimed = true;
          }
        }
#endif
        note_unclaimed(pending, obj.object_id, instance, claimed);
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

  auto decode_status = decoder.status();
  // The transport pads a fixed-length frame to the slot with 0xFF, which is not
  // a BTHome object id - so the decoder stopping on exactly that id is the end
  // of the sender's data, not a fault. Recognised here rather than by trimming
  // the frame beforehand, because 0xFF is only padding in this position: inside
  // a value it is an ordinary byte, and cutting it there loses measurements.
  if (decode_status == BTHome::DecodeStatus::UnknownId && obj.object_id == 0xFF) {
    decode_status = BTHome::DecodeStatus::End;
  }
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

  // BTHome makes the packet id optional, and for measurements its absence costs
  // nothing - the same reading is published a few times over. For an event it
  // is the difference between one press and three, because there is then
  // nothing by which a repeat can be told from a new press. Measured on the
  // bench: three copies of one frame, three button events. Said once per
  // device; the sender will not start including one halfway through.
  if (pending.packet_id < 0 &&
      (pending.button_count > 0 || pending.dimmer_count > 0 || pending.command_count > 0) &&
      !this->warned_no_packet_id_) {
    this->warned_no_packet_id_ = true;
    ESP_LOGW(TAG,
             "%s: event objects without a packet id - repeats cannot be told from new "
             "events, so every copy the sender broadcasts fires again",
             this->sender_id_text_);
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

  // Said once per object, at DEBUG rather than VERBOSE, because this is the
  // line that turns "the remote sends nothing useful" into "the remote sends
  // this and you have not asked for it". Once configured it falls silent; the
  // per-object VERBOSE lines above remain for watching values go by.
  for (uint8_t i = 0; i < pending.unclaimed_count; i++) {
    const uint16_t key = pending.unclaimed[i];
    if (std::find(this->reported_unclaimed_.begin(), this->reported_unclaimed_.end(), key) !=
        this->reported_unclaimed_.end()) {
      continue;
    }
    this->reported_unclaimed_.push_back(key);
    const uint8_t object_id = static_cast<uint8_t>(key >> 8);
    const char *name = object_type_name(object_id);
    ESP_LOGD(TAG, "%s: object 0x%02X#%u (%s) has no entity configured for it",
             this->sender_id_text_, static_cast<unsigned>(object_id),
             static_cast<unsigned>(key & 0xFF),
             name != nullptr ? name : "not mapped by this version");
  }

  // Commands fire in payload order and are not indexed: unlike a button, a
  // second command object is the next instruction rather than a second input.
  for (uint8_t i = 0; i < pending.command_count; i++) {
    const std::string name = command_event_name(pending.command_opcodes[i]);
    const int steps = static_cast<int>(pending.command_args[i]);
    ESP_LOGD(TAG, "%s: command %s (%d)", this->sender_id_text_, name.c_str(), steps);
    for (auto *trigger : this->command_triggers_) {
      trigger->trigger(name, steps);
    }
  }

#ifdef USE_SENSOR
  for (auto &slot : this->object_sensors_) {
    if (slot.has_pending && slot.sensor != nullptr) {
      slot.sensor->publish_state(slot.pending);
    }
  }
#endif

#ifdef USE_BINARY_SENSOR
  for (auto &slot : this->object_binary_sensors_) {
    if (slot.has_pending && slot.sensor != nullptr) {
      slot.sensor->publish_state(slot.pending);
    }
  }
#endif

#ifdef USE_TEXT_SENSOR
  for (auto &slot : this->object_text_sensors_) {
    if (!slot.has_pending || slot.sensor == nullptr) {
      continue;
    }
    std::string value;
    if (slot.object_id == static_cast<uint8_t>(BTHome::ObjectId::Raw)) {
      // Raw is bytes, not characters: a zero in the middle would end a string
      // and anything above 0x7F is not printable. Hex, uppercase and without
      // separators - the form the frame itself is written in.
      static const char HEX[] = "0123456789ABCDEF";
      value.reserve(static_cast<size_t>(slot.length) * 2);
      for (uint8_t i = 0; i < slot.length; i++) {
        value.push_back(HEX[slot.bytes[i] >> 4]);
        value.push_back(HEX[slot.bytes[i] & 0x0F]);
      }
    } else {
      value.assign(reinterpret_cast<const char *>(slot.bytes), slot.length);
    }
    // Only on change, as the device name already was: a text object is a
    // sender's identity far more often than a reading, and republishing the
    // same string with every broadcast fills the recorder with nothing.
    if (!slot.sensor->has_state() || slot.sensor->state != value) {
      slot.sensor->publish_state(value);
    }
  }

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
  // Only the packet id is aged out here, never the replay counter of an
  // encrypted device: that one exists precisely to outlive quiet periods, and
  // forgetting it after fifteen seconds of silence would hand an attacker a
  // window to replay a captured frame in.
  //
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

void NRF24BTHomeDevice::dump_config() const {
  ESP_LOGCONFIG(TAG, "  Device: %s", this->sender_id_text_);
  if (this->timeout_ms_ == 0) {
    ESP_LOGCONFIG(TAG, "    Timeout: none (offline detection disabled)");
  } else {
    ESP_LOGCONFIG(TAG, "    Timeout: %u ms", static_cast<unsigned>(this->timeout_ms_));
  }

  unsigned sensors = 0, binaries = 0, texts = 0;
#ifdef USE_SENSOR
  sensors = static_cast<unsigned>(this->object_sensors_.size()) +
            (this->last_seen_sensor_ != nullptr ? 1u : 0u);
#endif
#ifdef USE_BINARY_SENSOR
  binaries = static_cast<unsigned>(this->object_binary_sensors_.size()) +
             (this->connected_sensor_ != nullptr ? 1u : 0u);
#endif
#ifdef USE_TEXT_SENSOR
  texts = static_cast<unsigned>(this->object_text_sensors_.size()) +
          (this->name_text_sensor_ != nullptr ? 1u : 0u) +
          (this->firmware_text_sensor_ != nullptr ? 1u : 0u) +
          (this->sender_id_text_sensor_ != nullptr ? 1u : 0u);
#endif
  ESP_LOGCONFIG(TAG, "    Entities: %u sensor, %u binary sensor, %u text sensor", sensors,
                binaries, texts);
#ifdef USE_BTHOME_ENCRYPTION
  // Worth a line of its own: an encrypted sender talking to a device without a
  // key, or the reverse, goes quiet with only a warning per frame to say so, and
  // this is where one can see which of the two is configured.
  ESP_LOGCONFIG(TAG, "    Encryption: %s", this->encrypted_ ? "AES-128-CCM" : "none");
#endif
  ESP_LOGCONFIG(TAG, "    Triggers: %u on_button, %u on_dimmer, %u on_command",
                static_cast<unsigned>(this->button_triggers_.size()),
                static_cast<unsigned>(this->dimmer_triggers_.size()),
                static_cast<unsigned>(this->command_triggers_.size()));
}

void NRF24BTHomeHub::dump_config() {
  ESP_LOGCONFIG(TAG, "nRF24 BTHome receiver:");
  for (auto *dev : this->devices_) {
    dev->dump_config();
  }
}

}  // namespace nrf24_bthome
}  // namespace esphome
