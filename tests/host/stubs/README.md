# Host stubs

Just enough of ESPHome for `components/nrf24_bthome/nrf24_bthome.cpp` to compile
and run on a development machine. They exist so the component's own logic - the
part between "a frame arrived" and "an entity was published" - can be checked in
CI instead of only in a lab with a hub and two dongles.

Two rules keep this honest:

**The harness compiles the real source.** Not a copy, not a reimplementation.
What differs between here and the firmware is only the environment; the logic
under test is the same file that gets flashed.

**These stubs prove nothing about ESPHome.** They provide behaviour, not
fidelity: a `publish_state` that prints instead of talking to the API, a
`millis()` a test can set. Whether the *real* headers still fit the component is
what the `esphome compile` job in CI answers, and that job stays the authority
for it. If a stub and ESPHome ever disagree, ESPHome is right.
