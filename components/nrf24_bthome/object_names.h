#pragma once

#include <stdint.h>

// BTHome object id -> the key the YAML uses for it, for one diagnostic: naming
// an object a sender broadcasts that no entity was configured to take. A bare
// "object 0x03" leaves the reader to go looking; "humidity" is what they would
// have to write anyway.
//
// GENERATED from SENSOR_TYPES in sensor.py and BINARY_TYPES in binary_sensor.py,
// which are the tables the configuration schema itself is built from - so a name
// here is a name that works in a config. tests/test_sensor_types.py regenerates
// it and fails if this file has drifted, which is what keeps that true.
//
// Costs about 1.5 KB of flash and no RAM. Not conditional: a receiver whose
// remote sends something unexpected is exactly the one that needs the line.

namespace esphome {
namespace nrf24_bthome {

struct ObjectName {
  uint8_t object_id;
  const char *key;
};

// Sorted by object id. Ids the schema has no key for are absent, and
// object_type_name() answers nullptr for those.
const ObjectName OBJECT_NAMES[] = {
    {0x01, "battery"},
    {0x02, "temperature"},
    {0x03, "humidity"},
    {0x04, "pressure"},
    {0x05, "illuminance"},
    {0x06, "mass"},
    {0x07, "mass_lb"},
    {0x08, "dewpoint"},
    {0x09, "count"},
    {0x0A, "energy"},
    {0x0B, "power"},
    {0x0C, "voltage"},
    {0x0D, "pm2_5"},
    {0x0E, "pm10"},
    {0x0F, "generic"},
    {0x10, "power"},
    {0x11, "opening"},
    {0x12, "co2"},
    {0x13, "tvoc"},
    {0x14, "moisture"},
    {0x15, "battery_low"},
    {0x16, "battery_charging"},
    {0x17, "carbon_monoxide"},
    {0x18, "cold"},
    {0x19, "connectivity"},
    {0x1A, "door"},
    {0x1B, "garage_door"},
    {0x1C, "gas"},
    {0x1D, "heat"},
    {0x1E, "light"},
    {0x1F, "lock"},
    {0x20, "moisture"},
    {0x21, "motion"},
    {0x22, "moving"},
    {0x23, "occupancy"},
    {0x24, "plug"},
    {0x25, "presence"},
    {0x26, "problem"},
    {0x27, "running"},
    {0x28, "safety"},
    {0x29, "smoke"},
    {0x2A, "sound"},
    {0x2B, "tamper"},
    {0x2C, "vibration"},
    {0x2D, "window"},
    {0x2E, "humidity_u8"},
    {0x2F, "moisture_u8"},
    {0x3D, "count"},
    {0x3E, "count"},
    {0x3F, "rotation"},
    {0x40, "distance_mm"},
    {0x41, "distance_m"},
    {0x42, "duration"},
    {0x43, "current"},
    {0x44, "speed"},
    {0x45, "temperature_c1"},
    {0x46, "uv_index"},
    {0x47, "volume"},
    {0x48, "volume_ml"},
    {0x49, "volume_flow_rate"},
    {0x4A, "voltage_centi"},
    {0x4B, "gas"},
    {0x4C, "gas"},
    {0x4D, "energy"},
    {0x4E, "volume_u32"},
    {0x4F, "water"},
    {0x50, "timestamp"},
    {0x51, "acceleration"},
    {0x52, "gyroscope"},
    {0x55, "volume_storage"},
    {0x56, "conductivity"},
    {0x57, "temperature_s8"},
    {0x58, "temperature_s8_035"},
    {0x59, "count"},
    {0x5A, "count"},
    {0x5B, "count"},
    {0x5C, "power"},
    {0x5D, "current"},
    {0x5E, "direction"},
    {0x5F, "precipitation"},
    {0x60, "channel"},
    {0x61, "rotational_speed"},
    {0x62, "speed_s32"},
    {0x63, "acceleration_s32"},
    {0x64, "light_level"},
    {0x65, "settings_revision"},
};

inline const char *object_type_name(uint8_t object_id) {
  for (const auto &entry : OBJECT_NAMES) {
    if (entry.object_id == object_id) {
      return entry.key;
    }
  }
  return nullptr;
}

}  // namespace nrf24_bthome
}  // namespace esphome
