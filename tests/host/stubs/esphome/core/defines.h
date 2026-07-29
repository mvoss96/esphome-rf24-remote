#pragma once

// Every optional platform on, so the harness compiles all four #ifdef'd paths
// through the component. A build that left one out would silently stop testing
// it.
#define USE_SENSOR
#define USE_TEXT_SENSOR
#define USE_BINARY_SENSOR
#define USE_TIME
