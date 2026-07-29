// Runs the real nrf24_bthome component on the host, so what happens between "a
// frame arrived" and "an entity was published" can be checked without a radio.
//
// Two devices are registered, each with an entity or a trigger on every path the
// component has, and a scenario is read from stdin:
//
//     FRAME <hex>     a whole frame, sender id included, handed to the hub - so
//                     sender matching and the rejection paths are covered too
//     CLOCK <ms>      set millis(); makes timeouts and the wraparound instant
//     EPOCH <s|none>  the clock last_seen publishes, or an invalid one
//     TICK            run the hub's loop, which sweeps the timeouts
//     DUMP            run dump_config
//     MARK <text>     echoed back, so a test can find its way in the output
//
// Everything the component does comes back as one line: LOG for its own
// messages, PUBLISH for an entity, TRIGGER for an automation. The hardware
// benches already read the component's verdicts out of its log; phrasing both
// the same way keeps their expectations comparable.
//
// Built by tests/test_device_logic.py, which fetches the pinned bthome-cpp
// first; see build_probe() there for the exact command.

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "components/nrf24_bthome/nrf24_bthome.h"

using esphome::binary_sensor::BinarySensor;
using esphome::nrf24_bthome::ButtonTrigger;
using esphome::nrf24_bthome::DimmerTrigger;
using esphome::nrf24_bthome::NRF24BTHomeDevice;
using esphome::nrf24_bthome::NRF24BTHomeHub;
using esphome::sensor::Sensor;
using esphome::text_sensor::TextSensor;

namespace {

// The triggers only report; what they would run is the user's automation, and
// that is not what this harness is about.
class WatchingButton : public ButtonTrigger {
 public:
  WatchingButton(NRF24BTHomeDevice *device, std::string label)
      : ButtonTrigger(device), label_(std::move(label)) {}
  void trigger(uint8_t button, std::string event) override {
    std::printf("TRIGGER %s button %u %s\n", this->label_.c_str(),
                static_cast<unsigned>(button), event.c_str());
    std::fflush(stdout);
  }

 private:
  std::string label_;
};

class WatchingDimmer : public DimmerTrigger {
 public:
  WatchingDimmer(NRF24BTHomeDevice *device, std::string label)
      : DimmerTrigger(device), label_(std::move(label)) {}
  void trigger(uint8_t dimmer, int steps) override {
    std::printf("TRIGGER %s dimmer %u %d\n", this->label_.c_str(),
                static_cast<unsigned>(dimmer), steps);
    std::fflush(stdout);
  }

 private:
  std::string label_;
};

bool parse_hex(const std::string &text, std::vector<uint8_t> &out) {
  if (text.size() % 2 != 0) return false;
  for (size_t i = 0; i < text.size(); i += 2) {
    unsigned byte = 0;
    if (std::sscanf(text.substr(i, 2).c_str(), "%2x", &byte) != 1) return false;
    out.push_back(static_cast<uint8_t>(byte));
  }
  return true;
}

}  // namespace

int main() {
  esphome::time::RealTimeClock clock;
  clock.set_now(1700000000);

  NRF24BTHomeHub hub;

  // Device A carries one entity per path the component can take.
  NRF24BTHomeDevice a;
  a.set_sender_id({0xAA, 0x01, 0x00, 0x01});
  a.set_timeout(15000);
  a.set_time(&clock);

  Sensor a_battery("A.battery"), a_temperature("A.temperature");
  Sensor a_temperature2("A.temperature2"), a_voltage("A.voltage"), a_last_seen("A.last_seen");
  a.add_object_sensor(0x01, 1, &a_battery);
  a.add_object_sensor(0x02, 1, &a_temperature);
  a.add_object_sensor(0x02, 2, &a_temperature2);
  a.add_object_sensor(0x0C, 1, &a_voltage);
  a.set_last_seen_sensor(&a_last_seen);

  TextSensor a_name("A.device_name"), a_firmware("A.firmware"), a_sender("A.sender_id");
  TextSensor a_text("A.text"), a_text2("A.text2"), a_raw("A.raw");
  a.set_name_text_sensor(&a_name);
  a.set_firmware_text_sensor(&a_firmware);
  a.set_sender_id_text_sensor(&a_sender);
  a.add_object_text_sensor(0x53, 1, &a_text);
  a.add_object_text_sensor(0x53, 2, &a_text2);
  a.add_object_text_sensor(0x54, 1, &a_raw);

  BinarySensor a_connected("A.connected"), a_motion("A.motion");
  a.set_connected_binary_sensor(&a_connected);
  a.add_object_binary_sensor(0x21, 1, &a_motion);

  WatchingButton a_button(&a, "A");
  WatchingDimmer a_dimmer(&a, "A");

  // Device B exists so attribution is testable: an event on one sender must not
  // appear on the other, and each keeps its own dedup state.
  NRF24BTHomeDevice b;
  b.set_sender_id({0xAA, 0x01, 0x00, 0x02});
  b.set_timeout(15000);
  Sensor b_battery("B.battery");
  b.add_object_sensor(0x01, 1, &b_battery);
  BinarySensor b_connected("B.connected");
  b.set_connected_binary_sensor(&b_connected);
  WatchingButton b_button(&b, "B");

  // Device C takes encrypted payloads. Same paths as A, minus the ones the
  // frame budget no longer has room for: every frame costs eight bytes of
  // counter and MIC before an object is in it.
  NRF24BTHomeDevice c;
  c.set_sender_id({0xAA, 0x01, 0x00, 0x03});
  c.set_timeout(15000);
  Sensor c_battery("C.battery");
  c.add_object_sensor(0x01, 1, &c_battery);
  BinarySensor c_connected("C.connected");
  c.set_connected_binary_sensor(&c_connected);
  WatchingButton c_button(&c, "C");
  // The key from the BTHome specification's own worked example, so a payload
  // built here can be checked against a third implementation by hand. The nonce
  // MAC is what the component's codegen derives: the sender id, zero-extended.
  c.set_encryption_key({0x23, 0x1D, 0x39, 0xC1, 0xD7, 0xCC, 0x1A, 0xB1, 0xAE, 0xE2, 0x24,
                        0xCD, 0x09, 0x6D, 0xB9, 0x32});
  c.set_nonce_mac({0xAA, 0x01, 0x00, 0x03, 0x00, 0x00});

  hub.register_device(&a);
  hub.register_device(&b);
  hub.register_device(&c);
  // What setup() would do, minus registering with the radio - there is none.
  a.publish_static_info();
  b.publish_static_info();
  c.publish_static_info();

  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream in(line);
    std::string command;
    in >> command;

    if (command == "FRAME") {
      std::string hex;
      in >> hex;
      std::vector<uint8_t> frame;
      if (!parse_hex(hex, frame)) {
        std::printf("ERROR bad hex %s\n", hex.c_str());
        continue;
      }
      // The padded flag says the pipe has a fixed size, which a 32-byte frame
      // here stands for. The component no longer acts on it - it finds the end
      // of the data by walking the objects - but it is what the radio passes.
      hub.on_nrf24_frame(2, frame.data(), static_cast<uint8_t>(frame.size()),
                         frame.size() == 32);
    } else if (command == "CLOCK") {
      unsigned long ms = 0;
      in >> ms;
      esphome::stub_clock::now_ms() = static_cast<uint32_t>(ms);
    } else if (command == "EPOCH") {
      std::string value;
      in >> value;
      if (value == "none") {
        clock.set_now(0, false);
      } else {
        clock.set_now(static_cast<uint32_t>(std::strtoul(value.c_str(), nullptr, 10)));
      }
    } else if (command == "TICK") {
      hub.loop();
    } else if (command == "DUMP") {
      hub.dump_config();
    } else if (command == "MARK") {
      std::string rest;
      std::getline(in, rest);
      std::printf("MARK%s\n", rest.c_str());
      std::fflush(stdout);
    } else {
      std::printf("ERROR unknown command %s\n", command.c_str());
    }
  }
  return 0;
}
