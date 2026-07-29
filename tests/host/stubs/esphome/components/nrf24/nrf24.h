#pragma once

// The real header, reached under the include path the component writes. Not a
// stub: nrf24.h is what declares NRF24Listener, and a copy of it here could
// drift from the interface the component actually implements.
//
// Resolved through the second include directory, the repository root.
#include "components/nrf24/nrf24.h"
