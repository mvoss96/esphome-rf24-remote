"""One test vector per mapped BTHome measurement type.

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
"""

# key, object id, raw integer on the wire, little-endian value bytes,
# expected physical value, expected unit, expected decimals
VECTORS = [
    # key            id    raw        bytes       value       unit       dec
    ("battery",      0x01, 85,        "55",       85.0,       "%",       0),
    ("temperature",  0x02, 2345,      "2909",     23.45,      "°C", 2),
    ("humidity",     0x03, 4865,      "0113",     48.65,      "%",       2),
    ("pressure",     0x04, 101325,    "CD8B01",   1013.25,    "hPa",     2),
    ("illuminance",  0x05, 123456,    "40E201",   1234.56,    "lx",      2),
    ("mass",         0x06, 8030,      "5E1F",     80.30,      "kg",      2),
    ("dewpoint",     0x08, -321,      "BFFE",     -3.21,      "°C", 2),
    ("count",        0x09, 42,        "2A",       42.0,       None,      0),
    ("energy",       0x0A, 1234567,   "87D612",   1234.567,   "kWh",     3),
    ("power",        0x0B, 345678,    "4E4605",   3456.78,    "W",       2),
    ("voltage",      0x0C, 3456,      "800D",     3.456,      "V",       3),
    ("pm2_5",        0x0D, 12,        "0C00",     12.0,       "µg/m³", 0),
    ("pm10",         0x0E, 34,        "2200",     34.0,       "µg/m³", 0),
    ("co2",          0x12, 1250,      "E204",     1250.0,     "ppm",     0),
    ("tvoc",         0x13, 321,       "4101",     321.0,      "µg/m³", 0),
    ("moisture",     0x14, 5555,      "B315",     55.55,      "%",       2),
    ("rotation",     0x3F, -123,      "85FF",     -12.3,      "°",  1),
    ("distance_mm",  0x40, 750,       "EE02",     750.0,      "mm",      0),
    ("distance_m",   0x41, 78,        "4E00",     7.8,        "m",       1),
    ("duration",     0x42, 12345,     "393000",   12.345,     "s",       3),
    ("current",      0x43, 1234,      "D204",     1.234,      "A",       3),
    ("speed",        0x44, 1337,      "3905",     13.37,      "m/s",     2),
    ("uv_index",     0x46, 50,        "32",       5.0,        None,      1),
    ("volume",       0x47, 2345,      "2909",     234.5,      "L",       1),
    ("gas",          0x4B, 1234,      "D20400",   1.234,      "m³", 3),
    ("conductivity", 0x56, 1234,      "D204",     1234.0,     "µS/cm", 0),
    ("precipitation", 0x5F, 123,      "7B00",     12.3,       "mm",      1),
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


def encoded(object_id, value_bytes):
    """The object as it appears in a BTHome payload: id byte, then the value."""
    return f"{object_id:02X}{value_bytes}"


def all_vectors():
    """Every vector, positive and negative, as (key, id, raw, hex, value, unit, dec)."""
    return list(VECTORS) + [
        (key, oid, raw, b, v, u, d) for key, oid, raw, b, v, u, d in NEGATIVE_VECTORS
    ]
