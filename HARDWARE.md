# Hardware List

This is the hardware the build actually uses. Everything in "On hand" is owned.

## On hand

| # | Item | Qty | Purpose | Notes |
| --- | --- | --- | --- | --- |
| 1 | Arduino UNO Q | 1 | Linux vision host (QRB2210) plus STM32U585 servo controller | Board image `20260528-558` |
| 2 | Arduino UNO Media Carrier (ASX00083) | 1 | Breaks the Q's bottom JMEDIA connector out to two 22-pin MIPI-CSI connectors | Fitted and enabled 2026-11-11 with both cameras as `type1-2lanes` |
| 3 | ArduCam 8MP camera v2.3 (IMX219) | 2 | One per eye, on MIPI-CSI ribbon cables | Both stream through libcamera and OpenCV. No hardware sync between them, so frames are aligned by timestamp |
| 4 | Hitec HS-322HD standard servo | 2 | X axis (pan), one per eye | Analog PWM servo, 4.8-6.0 V. Carries the tilt servo and the camera |
| 5 | Hitec HS-55 sub-micro servo | 2 | Y axis (tilt), one per eye | Analog PWM servo, 4.8-6.0 V, about 8 g. Carries only the camera |
| 6 | Pan/tilt mount | 2 | Holds each camera on its two servos | Keep the camera as close to the pivot axes as possible |
| 7 | USB-C power supply, 5 A | 1 | Powers the Q, the carrier and the cameras | The servos do not run from it (see "Power" below) |

## Still needed

| Item | Qty | Purpose | Notes |
| --- | --- | --- | --- |
| Regulated 5 V DC supply, 4 A or more | 1 | Servo power, separate from the Q | A 5 V / 4 A wall adapter with a barrel-jack-to-screw-terminal adapter is enough (see "Power" below) |
| Electrolytic capacitor, 1000 µF, 10 V or higher | 1 | Absorbs servo start-up spikes | Fit it across the servo supply close to the servos |
| Servo power distribution (4 x 3-pin headers) | 1 | Feeds 5 V and ground to the four servo plugs and brings out the four signal pins | A strip of perfboard with header pins will do |
| Rigid checkerboard target | 1 | Intrinsic and hand-eye calibration | Print it flat on a stiff board and write down the square size in mm |

### Body

| Item | Notes |
| --- | --- |
| [Chameleon Surveillance Camera](https://makerworld.com/en/models/3082701-chameleon-surveillance-camera#profileId-3472171) 3D model | Print it, then paint it using [Chameleon.jpg](Chameleon.jpg) as the reference. The eye sockets may need changes to fit the cameras and pan/tilt mounts. The HS-322HD is a standard-size servo (about 40 x 20 x 37 mm), so check where it fits before printing |
| Filament, primer, acrylic paints | Pick colors from the reference photo |

## Power

There are two supplies with their grounds joined.

- **USB-C, 5 A:** the Q, the Media Carrier and both cameras.
- **5 V DC, 4 A:** the four servos only. Its positive rail never connects to the Q's 5V
  pin. Its ground connects to a Q GND pin so the PWM signals have a reference.

Why 4 A: the servo figures below are approximate and not taken from a datasheet in hand.
A stalled HS-322HD draws roughly 0.8 A and a stalled HS-55 roughly 0.6 A, so all four
stalled at once is about 2.8 A. Moving freely, each draws about 150-200 mA. A 4 A supply
covers the worst case with headroom. 5 V sits inside both servos' 4.8-6.0 V range.

Open points:

- Measure the real current with all four servos moving and with one held against a stop
  before trusting the budget.
- Whether one switch or connector should bring up both supplies together is not decided.
  Powering the servos before the Q is driving their signal pins can make them twitch.

## Servo notes

- **No position feedback.** These are plain PWM hobby servos, so the firmware knows only
  the angle it commanded, not where the eye actually is. The angle used for stereo
  geometry is the commanded pulse width converted through a per-axis calibration against
  the camera (see [PLAN.md](PLAN.md)).
- **Lag and backlash are invisible.** A servo takes time to reach a new command (about
  0.17-0.19 s per 60° at 4.8 V) and its gears have play. Limit how fast the firmware moves
  the command so the servo can keep up, and take measurements only once it has settled.
- **Signal.** One PWM pin per servo, four pins in total: 50 Hz, with a pulse of about
  900-2100 µs for about 90° of travel and 1500 µs at center. Find each axis's safe pulse
  limits on the bench before fitting it in the head.
- **Wiring.** Hitec plugs are yellow = signal, red = +5 V, black = ground.
- **Still to check:** that both servos respond to the Q's 3.3 V signal level, which pins
  to use, and whether the `Servo` library works on the `arduino:zephyr` core.

## Optional: analog FPV link

| # | Item | Qty | Purpose | Approx. cost (USD) | Notes |
| --- | --- | --- | --- | --- | --- |
| 8 | SP831TX video transmitter | 1 | 5.8 GHz analog video out | owned | Match its band and channel to the receiver |
| 9 | Small analog FPV camera | 1 | Composite video source for the transmitter | ~15 | The CSI cameras don't output composite video |
| 10 | RX5808 receiver module | 1 | Headless 5.8 GHz receiver | 5-10 | Get a version with SPI access so software can tune it |
| 11 | USB UVC capture dongle (MS2109 type) | 1 | Digitizes the receiver's composite output | 10-15 | Needs a USB port, and the Q's only USB-C port is taken by power, so this would need a hub with power pass-through |
