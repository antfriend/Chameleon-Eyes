# Plan

This plan builds two servo-aimed cameras, chameleon-style, on an Arduino UNO Q. Each eye looks independently, and the pair computes stereo depth whenever their views overlap. The parts are listed in [HARDWARE.md](HARDWARE.md).

The UNO Q splits the work. Its STM32 microcontroller runs the servo loop and logs timestamped angles. Its Linux side (Qualcomm QRB2210, Debian) captures video from two IMX219 cameras over MIPI-CSI, through the UNO Media Carrier, and runs OpenCV. A separate analog 5.8 GHz FPV link (SP831TX transmitter) is optional and has its own section below.

Three design choices drive the plan:

- **Independent mounts.** Each eye is a separate IMX219 camera on its own ribbon cable and its own pan/tilt mount, not a rigid stereo board. The two cameras have no hardware frame sync, so frames are paired by timestamp.
- **Hobby servos, no feedback.** Each eye uses two PWM hobby servos: a Hitec HS-322HD for pan (X) and an HS-55 for tilt (Y). They don't report their position, so the angle used for stereo geometry is the commanded angle, mapped through a per-axis calibration against the camera and corrected online from the images.
- **Calibrate the motion.** Fixed stereo calibration won't work for moving eyes. Hand-eye calibration replaces it, and the relative pose of the eyes is computed from servo angles on every frame.

## Goals

There are five phases, each with a pass/fail check, so every stage produces something usable before the next one begins.

| Phase | Goal | Pass check |
| --- | --- | --- |
| 0. Bench bring-up | The UNO Q boots, both CSI cameras stream, and an MCU sketch talks to Linux over the Bridge | OpenCV returns a frame from each camera; a Python call toggles an MCU pin |
| 1. Single eye, one axis | One camera on one pan servo, with its commanded angle logged to Linux | Commanded angle vs. the angle the camera measures from a checkerboard agrees within 1°, approached from both directions; frame timestamps logged |
| 2. Two eyes, pan/tilt | Both cameras on two-axis mounts, driven independently | Both eyes track a target without jitter; both streams hold 640x480 at 30 fps or better |
| 3. Calibration | Intrinsics for each eye, then hand-eye calibration for each eye | Reprojection error under 1 px per eye; pivot offsets solved |
| 4. Moving-eye stereo | Live relative pose from servo angles, sparse depth first, then dense | Depth to a known-distance target within 10% at 0.5-2 m |

These thresholds are starting targets, not measured limits. Adjust them once phase 1 shows what the servos and the camera capture lag allow.

Stretch goals, only after phase 4 passes:

- Saccade-and-fixate behavior: one eye scans while the other holds a target.
- Add an analog camera feeding the SP831TX for a live FPV view.
- Publish gaze and depth data to the ESP32 Agent 32 nodes over serial or Wi-Fi.

## Architecture

```
                         Arduino UNO Q
 ┌──────────────────────────────┐        ┌───────────────────────────────────┐
 │ STM32 MCU                    │ Bridge │ Linux (QRB2210, Debian)           │
 │  servo control loop          │◄──────►│  CSI capture (libcamera)          │
 │  timestamped angle log       │        │  OpenCV: calibration, rectify     │
 └──────────────┬───────────────┘        │  ★ Pose + depth: join angles      │
                │ 4 PWM signals          │    with frames, compute stereo    │
                ▼                        └───────┬──────────────────┬────────┘
     ┌─────────────────────┐                     │ Media Carrier    │ serial / Wi-Fi
     │ 4 PWM servos on a   │             ┌───────┴───────┐   ┌──────┴────────────┐
     │ separate 5 V supply │             │ Left eye cam  │   │ ESP32 Agent 32    │
     │  L pan, L tilt      │             │ Right eye cam │   │ nodes (optional)  │
     │  R pan, R tilt      │             └───────────────┘   └───────────────────┘
     └─────────────────────┘
```

The STM32 side owns servo timing and angle logging. The Linux side owns video, calibration and depth. Each camera reaches it over a MIPI-CSI ribbon cable through the Media Carrier, and `linux/eye_capture.py` turns the raw sensor data into color frames for OpenCV (libcamera can't run both cameras at once on this board). The pose + depth stage (★) is the new work: it joins timestamped angles with camera frames. The optional ESP32 link lets existing Agent 32 nodes use the gaze and depth data.

## Build steps

Work in this order. Each step ends with a check, and if a check fails, stop and fix it before going on.

1. **Bring up the Q.** Flash board image 558 or later, fit the Media Carrier, enable both camera connectors with `arduino-linux-config`, and reboot. Check: `cam -l` lists two `imx219` cameras and `cam -c N --capture=5` streams from each. (Done 2026-11-11.)
2. **Capture test.** Grab frames from both eyes at once with `linux/eye_capture.py` (1640x1232 raw at 30 fps, converted to color at 820x616). Record frame rate, CPU load and dropped frames. Check: both eyes hold 30 fps for 5 minutes with no growth in dropped frames.
3. **Bridge test.** Write a minimal MCU sketch and a Python caller that pass a value back and forth over the Bridge. Check: round-trip latency logged.
4. **One servo.** Power the servo from the separate 5 V supply with its ground joined to the Q, drive its signal pin from the MCU, and find its safe pulse limits. Fit the pulse-to-angle map by measuring the angle with the camera and a checkerboard. Check: commanded and camera-measured angles agree within 1°, approached from both directions.
5. **Timestamping.** Have the MCU log (commanded angle, microsecond timestamp) and the Linux side log (frame, timestamp). Measure the offset between the two clocks and the camera capture lag with a blinking-LED or moving-target test.
6. **Mechanical build.** Print the mounts, place each camera so its optical center sits near the pivot axis, and give each ribbon cable a slack loop and strain relief. Check: no ribbon drag at the travel limits.
7. **Second eye, then both axes.** Repeat steps 4-6 for all four servos. Check: both eyes move at the same time while video holds its frame rate.
8. **Calibrate** using the pipeline below, then check depth against a target at a known distance.
9. **Behavior layer.** Add saccade, fixation and tracking only after depth checks out.

Record each completed step in the [changelog](#changelog) so a regression can be traced.

## Calibration pipeline

Moving eyes need their relative pose recomputed from servo angles on every frame pair. That takes one calibration step beyond ordinary stereo.

1. **Intrinsics, once per eye.** Shoot 20-30 checkerboard views and run `cv2.calibrateCamera`. Settle the image orientation first (both eyes currently show the scene upside down) and calibrate at the capture size the pipeline will use, because intrinsics belong to one resolution.
2. **Static stereo at the neutral pose.** With both eyes pointing straight ahead, run `cv2.stereoCalibrate` to get a baseline rotation and translation (R0, T0). The runtime model is checked against this.
3. **Hand-eye calibration per eye.** Fix the checkerboard in the scene and drive one eye through 15-30 pan/tilt angles. At each angle, record the servo pose and solve the board pose with `solvePnP`. Pass both sets to `cv2.calibrateHandEye` to get the camera's pose relative to the servo pivot. Repeat for the other eye, then fit the offset between the two pivots.
4. **Runtime geometry.** For each frame pair, combine the two servo angles with the calibrated transforms to get the eyes' relative pose. At the neutral pose this must reproduce R0 and T0.
5. **Depth.** When the eyes point nearly the same way and their views overlap well, run `cv2.stereoRectify` with the live extrinsics, then `StereoSGBM` for dense depth. When they diverge widely, match sparse features (ORB, or a learned matcher if the Q can run it) and call `cv2.triangulatePoints`.
6. **Online correction.** The servos give no feedback, so backlash and settling error go straight into the pose. Use epipolar residuals from matched features to refine the relative rotation with a small least-squares step each frame.

Timing rule: interpolate the MCU's timestamped angles to each frame's capture time. Until the camera capture lag has been measured, take calibration images only while the servos are stationary.

## Analog FPV link (optional)

The SP831TX is a 5.8 GHz analog video transmitter and needs a composite video source. The link has two stages: an RF receiver, then a digitizer.

- **Transmit side:** a small analog FPV camera feeds the SP831TX. The CSI eye cameras can't drive it.
- **Receive side, remotely tunable:** an RX5808 with SPI access, tuned by an ESP32 (or the Q's MCU), outputs composite video and an RSSI signal.
- **Digitize:** a USB UVC dongle (MS2109 type) turns the composite signal into `/dev/video` frames on the Q's Linux side. The Q's only USB-C port is taken by power, so the dongle needs a hub with power pass-through.
- **Simpler alternative:** an ROTG02-style receiver that shows up as a UVC webcam. Its channel can only be changed with buttons.

Before relying on the link: match the transmitter's band and channel to the receiver (its two-digit display shows the current setting), expect roughly 20-50 ms of latency with a good dongle, and confirm the dongle works on the Q's kernel with `lsusb` and `v4l2-ctl`. Audio, if you use it, rides on a separate subcarrier that some dongles don't capture.

**Regulatory note:** 5.8 GHz transmit power and channel rules vary by country, and some FPV channels fall outside amateur-radio and unlicensed allocations. Check your local rules before transmitting.

## Remote link: website, viewer Q and two-way audio

The eye Q shares its images through a website it serves itself, with no Internet involved. In the long run the main client is a second UNO Q with a screen, and the two boards also carry two-way audio through their Media Carrier speaker and microphone.

| Stage | What | Check |
| --- | --- | --- |
| R1. Website | `linux/eye_server.py` on the eye Q: a page with both eyes, an MJPEG stream and a snapshot per eye, and `/status`. Standard library plus OpenCV, so nothing to install | Both eyes play in a PC browser at `http://localhost:8080/` through `adb forward`, with the capture rate from `/status` recorded |
| R2. Network | A Wi-Fi link between the two Qs with no router and no Internet: the eye Q runs an access point and the viewer Q joins it | The viewer Q opens the page by the eye Q's address |
| R3. Viewer Q | The second Q shows the streams full screen on its display | Both eyes on screen within a few seconds of power-up, with the delay measured |
| R4. Audio | Each Q sends its microphone to the other's speaker | Speech is understandable both ways with no howling |

Notes:

- **The server has no login.** Anyone who can reach the port can watch, which is acceptable on a private access point and not on a shared network.
- **Audio stays out of the browser.** Browsers allow microphone capture only on HTTPS or localhost, and an offline board has no easy certificate. The plan is a small native sender and receiver on each Q instead, using ALSA or GStreamer.
- **Echo.** With an open speaker and microphone at both ends, each side hears itself back and the loop can howl. Start with push-to-talk, and add echo cancellation only if that proves too clumsy.
- **Sharing costs CPU.** JPEG encoding runs only while somebody is watching, but while they are, it competes with the software ISP and the stereo work.

What the board offers for the later stages (looked at 2026-11-15, nothing tried): `wlan0` supports access-point mode and the `arduino` user appears to have permission to start a hotspot; there is one ALSA sound card with playback and capture devices; and the image runs an XFCE desktop with Chromium installed, so the viewer Q can show the page in a full-screen browser. Still to do: start the access point, play and record through the carrier's speaker and microphone, and enable a display on the viewer Q.

## Risks and open questions

The biggest risk is timing. If the camera capture lag is large or variable, moving-eye stereo degrades quickly, so measuring it is the first real experiment.

| Risk or question | Why it matters | Mitigation |
| --- | --- | --- |
| Capture lag unknown or variable | Servo angle and frame must line up within a few ms for a good pose, and the frame passes through the sensor, the software ISP and GStreamer before OpenCV sees it | Measure early; shoot calibration frames while stationary; interpolate angles |
| No frame sync between the eyes | The two frames of a pair are exposed at different moments | Pair frames by timestamp; interpolate each eye's angle to its own frame time; compute depth only when the scene and eyes are slow enough |
| Single USB-C port on the Q | It carries power and the adb link; anything else on USB needs a hub with power pass-through | The cameras are on CSI, so the core build needs no hub. Only the optional FPV dongle does |
| Ribbon cables on moving eyes | A stiff ribbon loads the small tilt servo and pulls the eye off its commanded angle | Long, flexible ribbons with a slack loop; check for drag at the travel limits |
| Home-made image pipeline | `eye_capture.py` does its own exposure and white balance with no color matrix or lens correction, and each eye adjusts on its own, so the two images can differ in brightness | Geometry doesn't depend on color; lock both eyes to the same exposure if matching suffers |
| Dim light | Indoors the exposure sits at its 30 fps limit with high gain, which means noise and motion blur while an eye moves | Add light; shoot calibration frames while stationary |
| No servo feedback, backlash and flex | The commanded angle may not match where the eye actually points, and nothing reports the difference | Pulse-to-angle calibration per axis; limit command speed so the servo keeps up; online epipolar correction; stiff mounts |
| Servo current spikes | A dip on the Q's rail would reboot Linux or drop a camera | Separate 5 V 4 A servo supply with shared ground and a bulk capacitor (HARDWARE.md) |
| CPU load on the Q | Converting raw frames for two cameras, SGBM and feature matching compete for the CPU | Profile in phase 2; downscale before matching |

Open questions:

- How much travel does each eye need, and is the commanded angle accurate enough for depth without feedback?
- Does the project need the ESP32 Agent 32 nodes in the loop, or can the Q run everything?
- Is the FPV link a core feature or a later add-on?

## Next actions

- [ ] Fix the image orientation (both eyes show the scene upside down)
- [ ] Get a 5 V 4 A servo supply, a 1000 µF capacitor and a servo power header; confirm the HS-55 and HS-322HD accept the Q's 3.3 V signal
- [ ] Run step 2 of the build plan: the 5-minute frame-rate test on both eyes (steps 1 and 3 are done)
- [ ] Measure the camera capture lag with a blinking-LED test
- [ ] Play and record through the carrier's speaker and microphone (first half of stage R4)

## Changelog

| Date | Change | Result |
| --- | --- | --- |
| 2026-10-29 | Plan written | — |
| 2026-11-05 | Step 3, Bridge test: `firmware/eyes_mcu` flashed with arduino-cli; `linux/bridge_test.py` run on the Q with plain python3 over adb (`linux/qbridge.py` talks to `arduino-router` directly) | **Pass.** `set_led` toggled the MCU LED 6/6. Bridge RTT over 200 calls: min 4.5 ms, median 5.8 ms, p95 6.6 ms, max 8.3 ms. MCU-vs-Linux clock offset is measurable to ±2.9 ms this way, which is too coarse for step 5 on its own |
| 2026-11-05 | Phase 0 pin check: `LED_BUILTIN` (LED3_R) found to be active-low; `eyes_mcu` fixed (`kLedActiveHigh = false`) and reflashed | **Pass.** Red LED off at rest, lit 3/3 times by `set_led(True)` from Python, in step with the matrix. Phase 0 still needs the camera half (`/dev/video0` MJPEG, steps 1-2) |
| 2026-11-05 | Reflashed the Q from image 424 to **558** (`arduino-flasher-cli`) to get Media Carrier support: `arduino-linux-config` plus IMX219 overlays for both camera connectors | Carrier camera support is present, not yet enabled (no carrier yet). Router 0.9.0 broke `ping` for 0..127 (signed re-encoding); fixed by signed RPC params in `eyes_mcu`. Bridge got faster: median 5.0 ms, p95 5.1 ms, clock bound ±2.5 ms |
| 2026-11-11 | OpenCV installed on the Q with no network: 148 `.deb` files for `python3-opencv` downloaded on the PC, pushed over adb, installed with apt from local files. `eyes_mcu` and `linux/` reloaded over USB | **Pass.** `import cv2` gives 4.10.0 with numpy 2.2.4; GStreamer, FFmpeg and V4L2 backends present. Bridge test on the board: 200/200 calls, median 4.4 ms. Root filesystem at 74% (2.5 GB free) |
| 2026-11-11 | Media Carrier enabled: `arduino-linux-config carrier enable media-carrier camera0=type1-2lanes camera1=type1-2lanes`, then reboot | **Pass.** `cam -l` lists two `imx219` cameras; `cam -c N --capture=5` streams 5 full-resolution frames from each at 7–14 fps. Bridge still works after the reboot (200/200, median 4.5 ms). Venus nodes moved to `/dev/video8`/`9`. No OpenCV frame grab or image check yet |
| 2026-11-11 | First images: `linux/grab_frames.py` opens each eye with OpenCV through a `libcamerasrc` GStreamer pipeline and saves a 1024x768 JPEG | **Pass.** Both eyes return a recognisable colour frame and their views overlap. Images are a little soft, have a blue-green cast, and the scene is upside down in both. The script's warm-up rate (about 60 fps over 30 frames) is not a step-2 frame-rate measurement; the 5-minute 30 fps check is still to do |
| 2026-11-15 | Design change: the four steppers and driver boards are replaced by four PWM hobby servos (2 x HS-322HD for pan, 2 x HS-55 for tilt) on a separate 5 V 4 A supply. Plan, hardware list and README updated | Documents only; nothing wired or tested. The servos give no position feedback, so the phase 1 check now compares the commanded angle with a camera-measured one |
| 2026-11-15 | Plan brought in line with the cameras actually fitted: two IMX219 modules on MIPI-CSI through the Media Carrier, replacing the USB cameras and hub the plan was written for | Documents only. Phase 0 check, build steps 1-2, the architecture diagram, risks and next actions rewritten; USB bandwidth and dual-lens module risks dropped |
| 2026-11-15 | Remote link planned (stages R1-R4) and `linux/eye_server.py` written: a website on the Q with an MJPEG stream and snapshot per eye | Tested on the PC only, with `--test-pattern`: page, `/status`, snapshots, two viewers on one stream and an OpenCV client all work. **Not run on the Q** (it was not connected), so the cameras, frame rate and CPU load are untested |
| 2026-11-15 | Stage R1 on the Q. libcamera could not run both cameras at once (both routed through `msm_csid0`), so `linux/eye_capture.py` was written: its own `media-ctl` routes, raw 8-bit Bayer at 1640x1232 through `v4l2-ctl`, then debayer, auto exposure, grey-world white balance and gamma in Python. `eye_server.py` now uses it | **Pass**, viewed from the PC through `adb forward`. Both eyes capture at 30.0 fps together and each stream delivered 146 frames in 10 s (820x616, 15 fps cap). The server process used about 30% of one core idle and about 140% of one core (of four) with both streams watched. Both images are upright with neutral colour. In room light the exposure was at its 30 fps limit with analogue gain 5-8x, so expect noise and motion blur indoors. Run for about a minute only, not the 5-minute step-2 check |
| 2026-11-15 | Stage R2, first half: Wi-Fi access point `chameleon` started on the eye Q with `nmcli device wifi hotspot` (WPA2, profile `chameleon-ap`, no sudo) | Access point is up and the Q is `10.42.0.1`; the website answers on `http://10.42.0.1:8080/` from the Q itself. The profile does not start by itself after a reboot |
| 2026-11-15 | Stage R2 with a phone as the client: joined the `chameleon` Wi-Fi and opened `http://10.42.0.1:8080/` in the phone's browser | **Pass.** Both live streams play on the phone. The second-Q client (stage R3) is still to do. Start at boot is then installed on the board (crontab `@reboot` running `linux/start_eyes.sh`, and autoconnect on the `chameleon-ap` profile), with no sudo |
| 2026-11-15 | Start at boot checked by a power cycle (the board refuses a reboot over adb without root) | **Pass.** With nothing started by hand, the `chameleon` Wi-Fi came up, cron started `start_eyes.sh`, the server started first time, both eyes captured at 30.0 fps, and both streams played on the phone |
