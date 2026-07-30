#pragma once

// Every optional platform on, so the harness compiles all four #ifdef'd paths
// through the component. A build that left one out would silently stop testing
// it.
#define USE_SENSOR
#define USE_TEXT_SENSOR
#define USE_BINARY_SENSOR
#define USE_TIME

// The one define codegen only emits when a device carries an encryption_key.
// On here for the same reason as the rest: left off, the whole decryption path
// would compile to nothing and the harness would quietly stop testing it. Costs
// the harness a link against mbedtls, which the firmware links anyway.
#define USE_BTHOME_ENCRYPTION
