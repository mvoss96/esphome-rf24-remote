// Prints the register bits nrf24_config.h derives from a radio configuration,
// so tests/test_nrf24_config.py can hold them to expectations written down
// independently of the code that computes them.
//
// One configuration per stdin line:
//
//     <rate> <pa> <payload_size>:<auto_ack> ...
//     250 3 32:0 0:1
//
// rate is 250, 1000 or 2000; pa is 0..3; each pipe is its payload size (0 for
// dynamic) and whether auto-ack is on. Output per line:
//
//     MASKS <EN_RXADDR> <EN_AA> <DYNPD> <FEATURE> <RF_SETUP>
//
// Build: c++ -std=c++17 -I <components/nrf24> -o nrf24_config_probe nrf24_config_probe.cpp

#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "nrf24_config.h"

using esphome::nrf24::DataRate;
using esphome::nrf24::PALevel;
using esphome::nrf24::pipe_masks;
using esphome::nrf24::PipeSetup;
using esphome::nrf24::rf_setup_byte;

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream in(line);

    int rate_kbps = 0;
    int pa = 0;
    in >> rate_kbps >> pa;
    const DataRate rate = rate_kbps == 250   ? esphome::nrf24::NRF24_RATE_250KBPS
                          : rate_kbps == 2000 ? esphome::nrf24::NRF24_RATE_2MBPS
                                              : esphome::nrf24::NRF24_RATE_1MBPS;

    // Deliberately unbounded: a configuration with more pipes than the chip has
    // is one of the cases worth checking, and clamping it here would hide what
    // pipe_masks() does with it.
    std::vector<PipeSetup> pipes;
    std::string token;
    while (in >> token) {
      const size_t colon = token.find(':');
      if (colon == std::string::npos) continue;
      pipes.push_back(PipeSetup{
          static_cast<uint8_t>(std::stoi(token.substr(0, colon))),
          std::stoi(token.substr(colon + 1)) != 0});
    }

    const auto masks = pipe_masks(pipes.empty() ? nullptr : pipes.data(), pipes.size());
    std::printf("MASKS %02X %02X %02X %02X %02X\n", masks.enabled, masks.auto_ack, masks.dynamic,
                masks.feature, rf_setup_byte(rate, static_cast<PALevel>(pa)));
  }
  return 0;
}
