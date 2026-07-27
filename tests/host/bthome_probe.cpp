// A host stand-in for the part of NRF24BTHomeDevice::handle_service_data that
// reads measurement objects, built against the same bthome-cpp version the
// firmware pins. It exists so the sensor table can be checked without a radio:
// the component decides what a BTHome object id means for Home Assistant, and
// that decision is only correct if it agrees with what the library actually
// decodes.
//
// Two outputs, both consumed by tests/test_sensor_types.py:
//
//   LAYOUT <id> <kind> <width> <signed> <factor>
//       one line per object id this library version knows. The factor is what
//       makes the raw integer a physical value, so it also fixes how many
//       decimals a sensor can meaningfully show.
//
//   FRAME <n> SENSOR <id> <instance> <value>   /   FRAME <n> STATUS <status>
//       one block per hex payload read from stdin, in the same shape the
//       firmware logs at VERBOSE, including the per-payload instance count.
//
// Build: c++ -std=c++17 -I <bthome-cpp>/src -o bthome_probe bthome_probe.cpp

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "bthome-cpp.h"

namespace {

const char *kind_name(BTHome::ObjectKind kind) {
  switch (kind) {
    case BTHome::ObjectKind::Unknown: return "Unknown";
    case BTHome::ObjectKind::PacketId: return "PacketId";
    case BTHome::ObjectKind::Sensor: return "Sensor";
    case BTHome::ObjectKind::Binary: return "Binary";
    case BTHome::ObjectKind::ButtonEvent: return "ButtonEvent";
    case BTHome::ObjectKind::DimmerEvent: return "DimmerEvent";
    case BTHome::ObjectKind::CommandEvent: return "CommandEvent";
    case BTHome::ObjectKind::Text: return "Text";
    case BTHome::ObjectKind::Raw: return "Raw";
    case BTHome::ObjectKind::DeviceTypeId: return "DeviceTypeId";
    case BTHome::ObjectKind::FirmwareVersion: return "FirmwareVersion";
  }
  return "?";
}

const char *status_name(BTHome::DecodeStatus status) {
  switch (status) {
    case BTHome::DecodeStatus::Ok: return "Ok";
    case BTHome::DecodeStatus::End: return "End";
    case BTHome::DecodeStatus::BadHeader: return "BadHeader";
    case BTHome::DecodeStatus::Encrypted: return "Encrypted";
    case BTHome::DecodeStatus::Truncated: return "Truncated";
    case BTHome::DecodeStatus::UnknownId: return "UnknownId";
  }
  return "?";
}

bool parse_hex(const std::string &text, std::vector<uint8_t> &out) {
  std::string clean;
  for (char c : text) {
    if (!std::isspace(static_cast<unsigned char>(c))) clean.push_back(c);
  }
  if (clean.size() % 2 != 0) return false;
  for (size_t i = 0; i < clean.size(); i += 2) {
    unsigned byte = 0;
    if (std::sscanf(clean.substr(i, 2).c_str(), "%2x", &byte) != 1) return false;
    out.push_back(static_cast<uint8_t>(byte));
  }
  return true;
}

}  // namespace

int main() {
  for (unsigned id = 0; id <= 0xFFu; ++id) {
    const auto layout = BTHome::detail::object_layout(static_cast<uint8_t>(id));
    if (layout.kind == BTHome::ObjectKind::Unknown) continue;
    std::printf("LAYOUT 0x%02X %s %u %d %.9g\n", id, kind_name(layout.kind), layout.width,
                layout.is_signed ? 1 : 0, static_cast<double>(layout.factor));
  }

  std::string line;
  unsigned frame = 0;
  while (std::getline(std::cin, line)) {
    if (line.empty() || line[0] == '#') continue;
    frame++;
    std::vector<uint8_t> data;
    if (!parse_hex(line, data)) {
      std::printf("FRAME %u STATUS BadHex\n", frame);
      continue;
    }

    BTHome::Decoder decoder(data.data(), data.size());
    BTHome::Decoded obj{};
    // Instances are counted per payload and per object id, the way the
    // firmware does it: the k-th occurrence of an id addresses the sensor
    // configured with index k.
    // Eight distinct ids, the same bound the firmware uses - a 32-byte frame
    // cannot carry more, and a stand-in that counted further would not stand in.
    uint8_t seen_ids[8] = {0};
    uint8_t seen_instances[8] = {0};
    uint8_t seen_count = 0;
    auto instance_of = [&](uint8_t object_id) -> uint8_t {
      for (uint8_t i = 0; i < seen_count; i++) {
        if (seen_ids[i] == object_id) return ++seen_instances[i];
      }
      if (seen_count < sizeof(seen_ids)) {
        seen_ids[seen_count] = object_id;
        seen_instances[seen_count] = 1;
        seen_count++;
      }
      return 1;
    };

    while (decoder.next(obj)) {
      if (obj.kind == BTHome::ObjectKind::Sensor) {
        std::printf("FRAME %u SENSOR 0x%02X %u %.6f\n", frame, obj.object_id,
                    instance_of(obj.object_id), static_cast<double>(obj.value));
      } else if (obj.kind == BTHome::ObjectKind::Binary) {
        std::printf("FRAME %u BINARY 0x%02X %u %u\n", frame, obj.object_id,
                    instance_of(obj.object_id), obj.raw != 0 ? 1u : 0u);
      } else if (obj.kind == BTHome::ObjectKind::Text ||
                 obj.kind == BTHome::ObjectKind::Raw) {
        // As hex for both kinds: the test compares bytes, and going through a
        // string here would lose exactly what the raw object exists to carry.
        std::printf("FRAME %u BYTES 0x%02X %u ", frame, obj.object_id,
                    instance_of(obj.object_id));
        for (uint8_t i = 0; i < obj.length; i++) std::printf("%02X", obj.bytes[i]);
        std::printf("%s\n", obj.length == 0 ? "-" : "");
      }
    }
    // The object id goes out with the status because it is what decides the
    // outcome for UnknownId: the firmware treats a stop on 0xFF as the end of
    // the sender's data, that being the byte a fixed-length slot is padded with.
    std::printf("FRAME %u STATUS %s 0x%02X\n", frame, status_name(decoder.status()),
                obj.object_id);
  }
  return 0;
}
