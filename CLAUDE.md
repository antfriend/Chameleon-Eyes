# CLAUDE.md — Chameleon Eyes

## What this is

A chameleon robot head: two USB-camera eyes, each on its own pan/tilt bus-servo mount,
aimed independently and doing moving-eye stereo when their views overlap. The brain is an
**Arduino UNO Q**. Read [PLAN.md](PLAN.md) first (phases, build steps, pass checks); parts
are in [HARDWARE.md](HARDWARE.md). Record each completed build step in the PLAN.md
changelog.

The UNO Q is two computers on one board, and the code is split the same way:

| Half | Chip | Runs | Code |
| --- | --- | --- | --- |
| MCU | STM32U585 (Cortex-M33 @160 MHz), Zephyr-based Arduino core | servo loop, timestamped angle log | `firmware/eyes_mcu/` |
| Linux | Qualcomm QRB2210, Debian | USB video, OpenCV, calibration, depth | `linux/` |

They talk over an internal UART owned by `arduino-router` on the Linux side;
**Arduino_RouterBridge** turns it into RPC: `Bridge.provide(...)` on the MCU,
`Bridge.call(...)` from Python (`from arduino.app_utils import Bridge`).

## Layout

```
PLAN.md / HARDWARE.md   Plan of record and parts list
firmware/
  eyes_mcu/             MCU sketch (arduino-cli; folder name == .ino name)
linux/                  Python for the Q's Linux side (pushed to the board with adb)
  qbridge.py            Dependency-free Bridge client (msgpack-RPC to arduino-router)
  bridge_test.py        Phase 0 / step 3: LED toggle, Bridge RTT, MCU clock offset
.vscode/tasks.json      Setup / Compile / Upload UNO Q, List boards
```

## Build & deploy — arduino-cli (same approach as C:\git\robot_team)

Command-line Arduino, not App Lab and not PlatformIO. On Windows the live path is
`.vscode/tasks.json`, which calls `arduino-cli` by full path
(`C:\Program Files\Arduino CLI\arduino-cli.exe`) because VSCode's terminal caches a stale
PATH.

```bash
ACLI="/c/Program Files/Arduino CLI/arduino-cli.exe"
"$ACLI" lib update-index && "$ACLI" core install arduino:zephyr   # once
"$ACLI" board list                                                 # find the Q's port
"$ACLI" compile --fqbn arduino:zephyr:unoq firmware/eyes_mcu       # compile
"$ACLI" compile --upload -p COMx --fqbn arduino:zephyr:unoq firmware/eyes_mcu
```

- **FQBN `arduino:zephyr:unoq`**, core `arduino:zephyr` 1.1.0 ("Arduino Q Boards"). Board
  menu defaults: `link_mode=dynamic`, `wait_linux_boot=yes`.
- ⚠ **Refresh the library index before installing the core.** With a stale index the
  install fails on `Library 'Arduino_RouterBridge@0.4.4' not found`. Bridge, RPClite and
  MsgPack land in the sketchbook (`~/Documents/Arduino/libraries`), not in the core.
- **Upload goes over the USB-C via adb + remoteocd** (both installed with the core). The
  `-p` port is only used to look up the board's USB serial number (VID 0x2341, PID 0x0078);
  nothing is written to it.
- **The `.ino` preprocessor hoists function prototypes** above the first function, so any
  typedef/struct a function signature uses must be declared above every function.

## Running the Linux side — adb, plain python3

The board's system `python3` (3.13, Debian 13) has **no `arduino.app_utils` and no
`msgpack`**: those exist only inside App Lab's app containers. `linux/qbridge.py` speaks
msgpack-RPC straight to `arduino-router` on `/var/run/arduino-router.sock` (world-writable),
so no App Lab app and no pip install are needed. Scripts try `arduino.app_utils` first and
fall back to `qbridge`.

```bash
ADB=/c/Users/antfr/AppData/Local/Arduino15/packages/arduino/tools/adb/32.0.0/adb.exe
export MSYS_NO_PATHCONV=1            # Git Bash: stop /home/... being rewritten to C:/...
"$ADB" devices                        # the Q shows by USB serial number
"$ADB" push linux/qbridge.py linux/bridge_test.py /home/arduino/chameleon/
"$ADB" shell 'cd /home/arduino/chameleon && python3 bridge_test.py'
```

- **From the PC, too:** run any `linux/` script on Windows and `qbridge` sets up
  `adb forward tcp:5775 localfilesystem:/var/run/arduino-router.sock` itself, then talks
  TCP. Handy for poking RPCs, but every call also crosses USB + adbd (`Bridge.remote` is
  True), so **timings from the PC are not the board's**. `bridge_test.py` says so and logs
  to `bridge_log_remote.csv`. VS Code task "Run bridge_test on UNO Q" does the on-board run.
- Board login is user `arduino` (groups include `dialout`, `video`, `gpiod`, `docker`).
- ⚠ **Each Bridge call costs ~5.8 ms round trip** (min 4.5 ms, measured 2026-11-05). Don't
  poll per-servo per-frame over RPC; batch, or have the MCU push timestamped samples.
- ⚠ **The board's wall clock was wrong** (unix time read as Sept 2025 on 2026-11-05; it
  isn't on a network yet). Use `time.monotonic()` for measurements, not `time.time()`.

## UNO Q gotchas

- ⚠ **`Serial` is not a COM port.** On this board `Serial` and `Monitor` are routed to Linux
  through the router, and `arduino-cli monitor` has no monitor for it. Make the sketch
  observable another way: the **8×13 LED matrix** (`Arduino_LED_Matrix`, `draw()` takes one
  byte per pixel, row-major, 13 wide × 8 high, grayscale depth set by `setGrayscaleBits`)
  or an RPC the Linux side can call.
- **Hardware UARTs:** `Serial1` = `usart1` on header **D0 (RX, PB7) / D1 (TX, PB6)**, and it
  is also Zephyr's boot console, so boot text appears on it after a reset. `lpuart1` is the
  router link to Linux, so don't touch it. `usart3` (PB10/PB11) is the other free UART,
  a candidate for the half-duplex servo bus.
- **`LED_BUILTIN` = LED3_R (PH10) is ACTIVE-LOW**: `digitalWrite(LED_BUILTIN, LOW)` lights
  it (seen on the bench 2026-11-05). `eyes_mcu` handles it with `kLedActiveHigh = false`.
  The other RGB LEDs (LED3_G/B, LED4_R/G/B) are probably the same, but that hasn't been checked.
- **Bridge RPC:** `provide` handlers run on the Bridge's update thread; `provide_safe` ones
  run on the loop thread. Never `Bridge.call` from inside an RPC handler (MCU–Linux
  deadlock, per the library README).
- **Single USB-C port:** camera, hub and power share it (PLAN.md risks). Servos get their
  own supply with a shared ground, never the Q's rail.

## Relationship to robot_team

PLAN.md's stretch goal publishes gaze and depth to the robot_team ESP32 (A32) nodes. The
UNO Q has no ESP-NOW, so that link would be the robot_team **Toot** frame
(`C:\git\robot_team\firmware\libraries\Toot`, portable, `architectures=*`) over a wire or
Wi-Fi. Don't pull robot_team code into this repo until that phase.
