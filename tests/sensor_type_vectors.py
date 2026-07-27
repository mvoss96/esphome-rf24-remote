"""One test vector per mapped BTHome object.

The same table drives both checks, so they cannot disagree about what a type is
supposed to do:

  * tests/test_sensor_types.py decodes the vectors on the host against the
    pinned bthome-cpp, with no radio involved - suitable for CI.
  * the radio bench transmits them and reads the receiver's verdict off its log,
    which additionally proves the value reaches the configured entity with the
    unit and the number of decimals the table promises.

Values are deliberately not round: a wrong scale factor or a lost sign shows up
as a wrong number rather than as the same number. The raw field is the integer
on the wire, so a vector can be re-derived by hand from the BTHome spec instead
of from the library being tested.

Several vectors may share a key. BTHome states a count six ways and energy two,
all the same quantity at the same resolution, and the component maps them onto
one entity - so each of those ids needs its own vector.
"""

# key, object id, raw integer on the wire, little-endian value bytes,
# expected physical value, expected unit, expected decimals
VECTORS = [
    # key                id    raw          bytes         value        unit       dec
    ("battery",          0x01, 85,          "55",         85.0,        "%",       0),
    ("temperature",      0x02, 2345,        "2909",       23.45,       "°C", 2),
    ("humidity",         0x03, 4865,        "0113",       48.65,       "%",       2),
    ("pressure",         0x04, 101325,      "CD8B01",     1013.25,     "hPa",     2),
    ("illuminance",      0x05, 123456,      "40E201",     1234.56,     "lx",      2),
    ("mass",             0x06, 8030,        "5E1F",       80.30,       "kg",      2),
    ("mass_lb",          0x07, 17710,       "2E45",       177.10,      "lb",      2),
    ("dewpoint",         0x08, -321,        "BFFE",       -3.21,       "°C", 2),
    ("count",            0x09, 42,          "2A",         42.0,        None,      0),
    ("energy",           0x0A, 1234567,     "87D612",     1234.567,    "kWh",     3),
    ("power",            0x0B, 345678,      "4E4605",     3456.78,     "W",       2),
    ("voltage",          0x0C, 3456,        "800D",       3.456,       "V",       3),
    ("pm2_5",            0x0D, 12,          "0C00",       12.0,        "µg/m³", 0),
    ("pm10",             0x0E, 34,          "2200",       34.0,        "µg/m³", 0),
    ("co2",              0x12, 1250,        "E204",       1250.0,      "ppm",     0),
    ("tvoc",             0x13, 321,         "4101",       321.0,       "µg/m³", 0),
    ("moisture",         0x14, 5555,        "B315",       55.55,       "%",       2),
    ("humidity_u8",      0x2E, 47,          "2F",         47.0,        "%",       0),
    ("moisture_u8",      0x2F, 63,          "3F",         63.0,        "%",       0),
    ("count",            0x3D, 4660,        "3412",       4660.0,      None,      0),
    ("count",            0x3E, 305419896,   "78563412",   305419896.0, None,      0),
    ("rotation",         0x3F, -123,        "85FF",       -12.3,       "°",  1),
    ("distance_mm",      0x40, 750,         "EE02",       750.0,       "mm",      0),
    ("distance_m",       0x41, 78,          "4E00",       7.8,         "m",       1),
    ("duration",         0x42, 12345,       "393000",     12.345,      "s",       3),
    ("current",          0x43, 1234,        "D204",       1.234,       "A",       3),
    ("speed",            0x44, 1337,        "3905",       13.37,       "m/s",     2),
    ("temperature_c1",   0x45, -73,         "B7FF",       -7.3,        "°C", 1),
    ("uv_index",         0x46, 50,          "32",         5.0,         None,      1),
    ("volume",           0x47, 2345,        "2909",       234.5,       "L",       1),
    ("volume_ml",        0x48, 1500,        "DC05",       1500.0,      "mL",      0),
    ("volume_flow_rate", 0x49, 1234,        "D204",       1.234,       "m³/h", 3),
    ("voltage_centi",    0x4A, 240,         "F000",       24.0,        "V",       1),
    ("gas",              0x4B, 1234,        "D20400",     1.234,       "m³", 3),
    ("gas",              0x4C, 12345678,    "4E61BC00",   12345.678,   "m³", 3),
    ("energy",           0x4D, 987654321,   "B168DE3A",   987654.321,  "kWh",     3),
    ("volume_u32",       0x4E, 3456789,     "15BF3400",   3456.789,    "L",       3),
    ("water",            0x4F, 5678901,     "35A75600",   5678.901,    "L",       3),
    ("timestamp",        0x50, 1700000000,  "00F15365",   1700000000.0, None,     0),
    ("acceleration",     0x51, 9807,        "4F26",       9.807,       "m/s²", 3),
    ("gyroscope",        0x52, 12345,       "3930",       12.345,      "°/s", 3),
    ("volume_storage",   0x55, 250500,      "84D20300",   250.500,     "L",       3),
    ("conductivity",     0x56, 1234,        "D204",       1234.0,      "µS/cm", 0),
    ("temperature_s8",   0x57, -5,          "FB",         -5.0,        "°C", 0),
    ("temperature_s8_035", 0x58, -7,        "F9",         -2.45,       "°C", 2),
    ("count",            0x59, -42,         "D6",         -42.0,       None,      0),
    ("count",            0x5A, -4660,       "CCED",       -4660.0,     None,      0),
    ("count",            0x5B, -305419896,  "88A9CBED",   -305419896.0, None,     0),
    ("power",            0x5C, -123456,     "C01DFEFF",   -1234.56,    "W",       2),
    ("current",          0x5D, -1234,       "2EFB",       -1.234,      "A",       3),
    ("direction",        0x5E, 18000,       "5046",       180.0,       "°",  2),
    ("precipitation",    0x5F, 123,         "7B00",       12.3,        "mm",      1),
    ("channel",          0x60, 7,           "07",         7.0,         None,      0),
    ("rotational_speed", 0x61, 1450,        "AA05",       1450.0,      "RPM",     0),
    ("speed_s32",        0x62, -1234567,    "7929EDFF",   -1.234567,   "m/s",     6),
    ("acceleration_s32", 0x63, -9806650,    "C65C6AFF",   -9.806650,   "m/s²", 6),
    ("light_level",      0x64, 3,           "03",         3.0,         None,      0),
    ("settings_revision", 0x65, 2,          "02",         2.0,         None,      0),
]

# Signed types get a second vector below zero. A lost sign bit turns a frost
# warning into 655 degrees, and on the air a negative value is also the case
# where the last byte is 0xFF - the byte the transport pads a fixed-length slot
# with.
NEGATIVE_VECTORS = [
    # key           id    raw     bytes     value    unit       dec
    ("temperature", 0x02, -100,   "9CFF",   -1.00,   "°C", 2),
    ("temperature", 0x02, -1,     "FFFF",   -0.01,   "°C", 2),
    ("dewpoint",    0x08, -1234,  "2EFB",   -12.34,  "°C", 2),
    ("rotation",    0x3F, -1,     "FFFF",   -0.1,    "°",  1),
]

# Every BTHome binary object. All of them are one byte, so there is no scale or
# sign to get wrong - what a vector proves here is that the id reaches the
# entity the table names, and that both states arrive rather than only the one
# the sensor happened to start in.
BINARY_VECTORS = [
    # key                 id    byte  state
    ("generic",           0x0F, "01", True),
    ("power",             0x10, "01", True),
    ("opening",           0x11, "01", True),
    ("battery_low",       0x15, "01", True),
    ("battery_charging",  0x16, "01", True),
    ("carbon_monoxide",   0x17, "01", True),
    ("cold",              0x18, "01", True),
    ("connectivity",      0x19, "01", True),
    ("door",              0x1A, "01", True),
    ("garage_door",       0x1B, "01", True),
    ("gas",               0x1C, "01", True),
    ("heat",              0x1D, "01", True),
    ("light",             0x1E, "01", True),
    ("lock",              0x1F, "01", True),
    ("moisture",          0x20, "01", True),
    ("motion",            0x21, "01", True),
    ("moving",            0x22, "01", True),
    ("occupancy",         0x23, "01", True),
    ("plug",              0x24, "01", True),
    ("presence",          0x25, "01", True),
    ("problem",           0x26, "01", True),
    ("running",           0x27, "01", True),
    ("safety",            0x28, "01", True),
    ("smoke",             0x29, "01", True),
    ("sound",             0x2A, "01", True),
    ("tamper",            0x2B, "01", True),
    ("vibration",         0x2C, "01", True),
    ("window",            0x2D, "01", True),
    # The other state, on the two whose off-reading is the interesting one.
    ("motion",            0x21, "00", False),
    ("door",              0x1A, "00", False),
]


# The two variable-length objects, [length][bytes] on the wire. `payload` is
# what follows the id, `shown` what the entity is expected to publish - text as
# characters, raw as hex, because raw bytes are not a string.
TEXT_VECTORS = [
    # key     id    payload                     shown
    ("text",  0x53, "0A" + "6C61622D73656E736F72", "lab-sensor"),
    ("raw",   0x54, "04DEADBEEF",                  "DEADBEEF"),
    # A raw value with a zero in the middle and a byte above 0x7F: read as a
    # string this would come out cut short and mangled.
    ("raw",   0x54, "0400FF0041",                  "00FF0041"),
]


def encoded(object_id, value_bytes):
    """The object as it appears in a BTHome payload: id byte, then the value."""
    return f"{object_id:02X}{value_bytes}"


def all_vectors():
    """Every measurement vector, positive and negative."""
    return list(VECTORS) + list(NEGATIVE_VECTORS)
