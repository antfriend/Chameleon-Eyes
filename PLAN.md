# Plan

This plan builds two servo-aimed cameras, chameleon-style, on an Arduino UNO Q. Each eye looks independently, and the pair computes stereo depth whenever their views overlap. The parts are listed in [HARDWARE.md](HARDWARE.md).

The UNO Q splits the work. Its STM32 microcontroller runs the servo loop and logs timestamped angles. Its Linux side (Qualcomm QRB2210, Debian) captures video over USB and runs OpenCV. A separate analog 5.8 GHz FPV link (SP831TX transmitter) is optional and has its own section below.

Three design choices drive the plan:

- **Independent mounts.** Standard ELP stereo boards are rigid, so the eyes use either the flex-cable ("non-fixed") dual-lens variant or two separate USB modules on separate servos.
- **Feedback servos.** Stereo geometry needs the real angle of each eye, so the rig uses serial bus servos that report their position instead of PWM hobby servos.
- **Calibrate the motion.** Fixed stereo calibration won't work for moving eyes. Hand-eye calibration replaces it, and the relative pose of the eyes is computed from servo angles on every frame.

## Goals

There are five phases, each with a pass/fail check, so every stage produces something usable before the next one begins.

| Phase | Goal | Pass check |
| --- | --- | --- |
| 0. Bench bring-up | The UNO Q boots, a USB camera streams, and an MCU sketch talks to Linux over the Bridge | `/dev/video0` delivers MJPEG frames; a Python call toggles an MCU pin |
| 1. Single eye, one axis | One camera on one pan servo, with its angle read back to Linux | Commanded vs. read-back angle error under 1°; frame timestamps logged |
| 2. Two eyes, pan/tilt | Both cameras on two-axis mounts, driven independently | Both eyes track a target without jitter; both streams hold 640x480 at 30 fps or better |
| 3. Calibration | Intrinsics for each eye, then hand-eye calibration for each eye | Reprojection error under 1 px per eye; pivot offsets solved |
| 4. Moving-eye stereo | Live relative pose from servo angles, sparse depth first, then dense | Depth to a known-distance target within 10% at 0.5-2 m |

These thresholds are starting targets, not measured limits. Adjust them once phase 1 shows what the servos and USB latency allow.

Stretch goals, only after phase 4 passes:

- Saccade-and-fixate behavior: one eye scans while the other holds a target.
- Send one eye's analog camera feed to the SP831TX for a live FPV view.
- Publish gaze and depth data to the ESP32 Agent 32 nodes over serial or Wi-Fi.

## Architecture

```
                         Arduino UNO Q
 ┌──────────────────────────────┐        ┌───────────────────────────────────┐
 │ STM32 MCU                    │ Bridge │ Linux (QRB2210, Debian)           │
 │  servo control loop          │◄──────►│  USB video capture (MJPEG)        │
 │  timestamped angle log       │        │  OpenCV: calibration, rectify     │
 └──────────────┬───────────────┘        │  ★ Pose + depth: join angles      │
                │ half-duplex UART       │    with frames, compute stereo    │
                ▼                        └───────┬──────────────────┬────────┘
     ┌─────────────────────┐                     │ USB-C hub        │ serial / Wi-Fi
     │ Bus servo driver    │             ┌───────┴───────┐   ┌──────┴────────────┐
     │ 4 servos:           │             │ Left eye cam  │   │ ESP32 Agent 32    │
     │  L pan, L tilt      │             │ Right eye cam │   │ nodes (optional)  │
     │  R pan, R tilt      │             └───────────────┘   └───────────────────┘
     └─────────────────────┘
```

The STM32 side owns servo timing and angle logging. The Linux side owns video, calibration and depth. The pose + depth stage (★) is the new work: it joins timestamped angles with camera frames. The optional ESP32 link lets existing Agent 32 nodes use the gaze and depth data.

## Build steps

Work in this order. Each step ends with a check, and if a check fails, stop and fix it before going on.

1. **Bring up the Q.** Update the image, then run `lsusb` and `v4l2-ctl --list-devices` with the camera attached through the hub. Check: `v4l2-ctl --list-formats-ext` shows MJPEG modes.
2. **Capture test.** Grab frames with OpenCV or GStreamer at 640x480 and at 960p. Record frame rate, CPU load and USB errors. Check: 30 fps held for 5 minutes with no growth in dropped frames.
3. **Bridge test.** Write a minimal MCU sketch and a Python caller that pass a value back and forth over the Bridge. Check: round-trip latency logged.
4. **One servo.** Wire the driver, power the servo from its own supply, and read its position back from the MCU. Check: commanded and read-back angles agree within 1°.
5. **Timestamping.** Have the MCU log (angle, microsecond timestamp) and the Linux side log (frame, timestamp). Measure the offset between the two clocks and the USB video lag with a blinking-LED or moving-target test.
6. **Mechanical build.** Print the mounts, place each camera so its optical center sits near the pivot axis, and add strain relief to the cables. Check: no cable drag at the travel limits.
7. **Second eye, then both axes.** Repeat steps 4-6 for all four servos. Check: both eyes move at the same time while video holds its frame rate.
8. **Calibrate** using the pipeline below, then check depth against a target at a known distance.
9. **Behavior layer.** Add saccade, fixation and tracking only after depth checks out.

Record each completed step in the [changelog](#changelog) so a regression can be traced.

## Calibration pipeline

Moving eyes need their relative pose recomputed from servo angles on every frame pair. That takes one calibration step beyond ordinary stereo.

1. **Intrinsics, once per eye.** Shoot 20-30 checkerboard views and run `cv2.calibrateCamera`. Use `cv2.fisheye.calibrate` for lenses wider than about 120°. Lock focus if the lens allows it.
2. **Static stereo at the neutral pose.** With both eyes pointing straight ahead, run `cv2.stereoCalibrate` to get a baseline rotation and translation (R0, T0). The runtime model is checked against this.
3. **Hand-eye calibration per eye.** Fix the checkerboard in the scene and drive one eye through 15-30 pan/tilt angles. At each angle, record the servo pose and solve the board pose with `solvePnP`. Pass both sets to `cv2.calibrateHandEye` to get the camera's pose relative to the servo pivot. Repeat for the other eye, then fit the offset between the two pivots.
4. **Runtime geometry.** For each frame pair, combine the two servo angles with the calibrated transforms to get the eyes' relative pose. At the neutral pose this must reproduce R0 and T0.
5. **Depth.** When the eyes point nearly the same way and their views overlap well, run `cv2.stereoRectify` with the live extrinsics, then `StereoSGBM` for dense depth. When they diverge widely, match sparse features (ORB, or a learned matcher if the Q can run it) and call `cv2.triangulatePoints`.
6. **Online correction.** Servo backlash adds error. Use epipolar residuals from matched features to refine the relative rotation with a small least-squares step each frame.

Timing rule: interpolate the MCU's timestamped angles to each frame's capture time. Until the USB video lag has been measured, take calibration images only while the servos are stationary.

## Analog FPV link (optional)

The SP831TX is a 5.8 GHz analog video transmitter and needs a composite video source. The link has two stages: an RF receiver, then a digitizer.

- **Transmit side:** a small analog FPV camera feeds the SP831TX. UVC cameras can't drive it directly.
- **Receive side, remotely tunable:** an RX5808 with SPI access, tuned by an ESP32 (or the Q's MCU), outputs composite video and an RSSI signal.
- **Digitize:** a USB UVC dongle (MS2109 type) turns the composite signal into `/dev/video` frames on the Q's Linux side.
- **Simpler alternative:** an ROTG02-style receiver that shows up as a UVC webcam. Its channel can only be changed with buttons.

Before relying on the link: match the transmitter's band and channel to the receiver (its two-digit display shows the current setting), expect roughly 20-50 ms of latency with a good dongle, and confirm the dongle works on the Q's kernel with `lsusb` and `v4l2-ctl`. Audio, if you use it, rides on a separate subcarrier that some dongles don't capture.

**Regulatory note:** 5.8 GHz transmit power and channel rules vary by country, and some FPV channels fall outside amateur-radio and unlicensed allocations. Check your local rules before transmitting.

## Risks and open questions

The biggest risk is timing. If USB video lag is large or variable, moving-eye stereo degrades quickly, so measuring it is the first real experiment.

| Risk or question | Why it matters | Mitigation |
| --- | --- | --- |
| USB video lag unknown or variable | Servo angle and frame must line up within a few ms for a good pose | Measure early; shoot calibration frames while stationary; interpolate angles |
| Single USB-C port on the Q | Camera, hub and power share one port | Test that the hub carries data and PD before buying more parts |
| Flex-cable dual-lens module poorly documented | Sensor, lens and driver support haven't been verified | Order one unit to test, with row 2b of the hardware list as the fallback |
| USB 2.0 bandwidth | Two uncompressed streams won't fit | MJPEG only; 640x480 per eye at first |
| Servo backlash and flex | Read-back angle may not match where the eye actually points | Online epipolar correction; stiff mounts; preloaded gears |
| CPU load on the Q | Capture, decoding, SGBM and feature matching compete for the CPU | Profile in phase 2; downscale before matching |
| UNO Q camera driver status | The MIPI-CSI path may not be usable yet | Plan on USB; check Arduino's docs before changing course |

Open questions:

- Which servo family (Feetech or Dynamixel), and how much travel does each eye need?
- Does the project need the ESP32 Agent 32 nodes in the loop, or can the Q run everything?
- Is the FPV link a core feature or a later add-on?

## Next actions

- [ ] Confirm the USB hub carries data and PD at the same time
- [ ] Order one flex-cable dual-lens module and a pair of single USB cameras to compare
- [ ] Order four bus servos and a driver; confirm 3.3 V logic compatibility
- [ ] Run steps 1-3 of the build plan on the bench
- [ ] Measure USB video lag with a blinking-LED test

## Changelog

| Date | Change | Result |
| --- | --- | --- |
| 2026-10-29 | Plan written | — |
