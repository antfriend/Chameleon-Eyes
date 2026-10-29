# Hardware List

All prices are approximate (USD). Check part numbers against the seller's listing before ordering.

## Core build

At these prices the core build costs roughly $190-280.

| # | Item | Qty | Purpose | Approx. cost | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Arduino UNO Q | 1 | Linux vision host plus STM32 servo controller | 44-59 | Comes in 2 GB and 4 GB RAM versions. The 4 GB version helps if you run feature-matching models |
| 2 | Flex-cable dual-lens USB camera ("non-fixed", 2 MP, synchronized) | 1 | Two sensors on separate flex cables, one UVC device | ~30 | Confirm the sensor, lens mount and Linux UVC support with the seller first |
| 2b | *Alternative:* two single USB camera modules | 2 | Independent eyes, easier to buy | 15-30 each | No hardware sync, so you'll need to align frames by timestamp |
| 3 | Serial bus servos with position feedback | 4 | Pan and tilt for each eye | 12-20 each | Feetech STS series or Dynamixel class. PWM hobby servos can't report their true angle |
| 4 | Bus servo driver / UART adapter | 1 | Half-duplex serial bridge between the MCU and the servo bus | 8-12 | Must match the servo family and the Q's 3.3 V logic |
| 5 | Pan/tilt mounts | 2 | Hold each camera on its pivot | 0-15 | 3D print them, with the camera as close to the pivot axis as you can get it |
| 6 | Powered USB-C hub with PD pass-through | 1 | Powers the Q and connects the camera through its single USB-C port | 20-35 | Test that it carries data and power at the same time |
| 7 | Servo power supply (bus voltage per servo spec, 3 A or more) | 1 | Separate power rail for the servos | 15-20 | Share ground with the Q. Never power the servos from the Q |
| 8 | Rigid checkerboard target | 1 | Intrinsic and hand-eye calibration | 5-10 | Print it flat on a stiff board and write down the square size in mm |

### Body

| Item | Notes |
| --- | --- |
| [Chameleon Surveillance Camera](https://makerworld.com/en/models/3082701-chameleon-surveillance-camera#profileId-3472171) 3D model | Print it, then paint it using [Chameleon.jpg](Chameleon.jpg) as the reference. The eye sockets may need changes to fit the cameras and servo mounts |
| Filament, primer, acrylic paints | Pick colors from the reference photo |

## Optional: analog FPV link

| # | Item | Qty | Purpose | Approx. cost | Notes |
| --- | --- | --- | --- | --- | --- |
| 9 | SP831TX video transmitter | 1 | 5.8 GHz analog video out | owned | Match its band and channel to the receiver |
| 10 | Small analog FPV camera | 1 | Composite video source for the transmitter | ~15 | UVC cameras don't output composite video |
| 11 | RX5808 receiver module | 1 | Headless 5.8 GHz receiver | 5-10 | Get a version with SPI access so software can tune it |
| 12 | USB UVC capture dongle (MS2109 type) | 1 | Digitizes the receiver's composite output | 10-15 | The Q has only one USB-C port, so plug this into the hub from row 6 |

## Open decision: row 2 or row 2b?

Row 2 keeps the two eyes in hardware sync. Row 2b is easier to buy and replace. If the flex-cable module turns out to be poorly documented, start with row 2b.
