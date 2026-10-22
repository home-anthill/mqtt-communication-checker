# Changelog

## 2.0.0

### Features

- Support `level`, `altitude`, `co2`, and `ph` in feature selection and spec-based/fallback value generation. Publish an independently signed `level` alarm for `level=1`, following motion.
- Add `iaq`, `voc`, and `eco2` selection, ranges, and float JSON generation following the existing sensor path.
- Added `alarm-receiver` preflight, separate `mode` and `mode (error -1)` choices, and alarm publishing for motion and thermostat mode errors.
- add device feature spec support
- add --all to send all messages to all profiles
- add thermostat `mode` sensor feature
- support AC models with different fanSpeed and mode values

### Bugfixes

- use the right airpressure min and max values

### Chores

- update dependencies
