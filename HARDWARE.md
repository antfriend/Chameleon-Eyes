# Hardware List

This is the hardware the build actually uses. Everything in "On hand" is owned.

## On hand

| # | Item | Qty | Purpose | Notes |
| --- | --- | --- | --- | --- |
| 1 | Arduino UNO Q | 1 | Linux vision host (QRB2210) plus STM32U585 motor controller | Board image `20260528-558` |
| 2 | Arduino UNO Media Carrier (ASX00083) | 1 | Breaks the Q's bottom JMEDIA connector out to two 22-pin MIPI-CSI connectors | Fitted and enabled 2026-11-11 with both cameras as `type1-2lanes` |
| 3 | ArduCam 8MP camera v2.3 (IMX219) | 2 | One per eye, on MIPI-CSI ribbon cables | Both stream through libcamera and OpenCV. No hardware sync between them, so frames are aligned by timestamp |
| 4 | Stepper motor | 4 | Pan and tilt for each eye | Open loop: a stepper doesn't report its angle, so each axis needs a home reference (see below) |
| 5 | Stepper driver board | 4 | One per motor, driven from the STM32's GPIO | Check that the inputs accept the Q's 3.3 V logic |
| 6 | Pan/tilt mount | 2 | Holds each camera on its two motors | Keep the camera as close to the pivot axes as possible |
| 7 | USB-C power supply, 5 A | 1 | The only power source for the rig | See "Power" below |

## Still needed

| Item | Qty | Purpose | Notes |
| --- | --- | --- | --- |
| Rigid checkerboard target | 1 | Intrinsic and hand-eye calibration | Print it flat on a stiff board and write down the square size in mm |

### Body

| Item | Notes |
| --- | --- |
| [Chameleon Surveillance Camera](https://makerworld.com/en/models/3082701-chameleon-surveillance-camera#profileId-3472171) 3D model | Print it, then paint it using [Chameleon.jpg](Chameleon.jpg) as the reference. The eye sockets may need changes to fit the cameras and pan/tilt mounts |
| Filament, primer, acrylic paints | Pick colors from the reference photo |

## Power

One 5 A USB-C supply feeds everything. The Q has a single USB-C port, and the cameras draw
from the Q through the carrier. The motors must not draw their current through the Q's
rails: split the supply's 5 V ahead of the Q, so the driver boards get their own feed, and
join the grounds.

Open points:

- How the supply is split between the Q's USB-C port and the driver boards (breakout, or a
  second cable) is not decided.
- Four steppers plus the Q and two cameras have to fit in 5 A. Measure the motor current
  with all four energized before trusting it.

## Stepper notes

- **No position feedback.** The firmware counts steps, so the angle is only known relative
  to where the motor was at power-up. Each axis needs a homing method (a limit switch, an
  optical flag or a hard stop) before the angle log means anything.
- **Missed steps are silent.** Stereo geometry uses the counted angle, so keep speeds and
  accelerations well inside what the motors can hold.
- **GPIO count.** Four drivers need 8 pins as step/dir or 16 pins as four-wire coil drive,
  depending on the driver type.

## Optional: analog FPV link

| # | Item | Qty | Purpose | Approx. cost (USD) | Notes |
| --- | --- | --- | --- | --- | --- |
| 8 | SP831TX video transmitter | 1 | 5.8 GHz analog video out | owned | Match its band and channel to the receiver |
| 9 | Small analog FPV camera | 1 | Composite video source for the transmitter | ~15 | The CSI cameras don't output composite video |
| 10 | RX5808 receiver module | 1 | Headless 5.8 GHz receiver | 5-10 | Get a version with SPI access so software can tune it |
| 11 | USB UVC capture dongle (MS2109 type) | 1 | Digitizes the receiver's composite output | 10-15 | Needs a USB port, and the Q's only USB-C port is taken by power, so this would need a hub with power pass-through |
