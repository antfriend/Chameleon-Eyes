// eyes_mcu.ino — Chameleon Eyes, Arduino UNO Q MCU half (STM32U585, Zephyr core).
//
// PLAN.md Phase 0 / build step 3: "a minimal MCU sketch and a Python caller that pass a
// value back and forth over the Bridge. Check: round-trip latency logged." The Python
// caller is linux/bridge_test.py.
//
// The UNO Q is two computers on one board:
//   MCU  STM32U585 Cortex-M33 @160 MHz, Zephyr-based Arduino core   <- THIS SKETCH
//   MPU  Qualcomm QRB2210, Debian Linux (cameras, OpenCV, Python)   <- linux/
// They talk over an internal UART owned by `arduino-router` on the Linux side;
// Arduino_RouterBridge turns it into RPC (Bridge.provide on this side, Bridge.call there).
//
// RPCs this sketch provides (all run on the loop thread via provide_safe):
//   ping(n)        -> n            round-trip latency probe (step 3)
//   set_led(on)    -> on           Phase 0 pass check: "a Python call toggles an MCU pin"
//   mcu_micros()   -> micros()     clock-offset probe for step 5 (timestamping); 32-bit,
//                                  wraps every ~71.6 min — the caller unwraps it
//   status()       -> text         one line: uptime, RPC count
//
// Output you can SEE without a serial monitor (on this board `Serial`/`Monitor` go to
// Linux through the router, and `arduino-cli monitor` has no monitor for it):
//   8x13 LED matrix — column 12: heartbeat dot walking once a second (sketch is alive);
//                     column 10: flashes on every RPC served (Linux is talking to us);
//                     columns 0-6: LED state as last set by set_led (filled = on).
//
// Build/flash (see CLAUDE.md):
//   arduino-cli compile --upload -p COMx --fqbn arduino:zephyr:unoq firmware/eyes_mcu

#include <Arduino.h>
#include <Arduino_RouterBridge.h>   // Bridge (RPC to Linux) + Monitor (the board's `Serial`)
#include <Arduino_LED_Matrix.h>

static const char* kBanner = "Chameleon Eyes MCU";   // grep-able banner literal

// LED_BUILTIN on the UNO Q is LED3_R (PH10), and it is ACTIVE-LOW: driving the pin LOW
// lights it. Seen on the bench 2026-11-05 — with this set to true the LED sat lit at idle
// and went dark on set_led(True), the opposite of the matrix block.
static const bool kLedActiveHigh = false;

static uint32_t gRpcCount = 0;
static uint32_t gLastRpcMs = 0;
static bool gLedOn = false;

// --- LED matrix (8 rows x 13 columns, one byte per pixel, 0..7 grayscale) ---------------
static Arduino_LED_Matrix gMatrix;
static const int MX_W = 13, MX_H = 8;
static uint8_t gPix[MX_W * MX_H];

static void px(int x, int y, uint8_t v) {
  if (x >= 0 && x < MX_W && y >= 0 && y < MX_H) gPix[y * MX_W + x] = v;
}

static void drawFace(uint32_t now) {
  memset(gPix, 0, sizeof(gPix));
  // columns 0-6: a filled block when the LED is on, an outline when off
  for (int y = 1; y < 7; ++y)
    for (int x = 0; x < 7; ++x) {
      bool edge = (y == 1 || y == 6 || x == 0 || x == 6);
      if (gLedOn || edge) px(x, y, gLedOn ? 7 : 2);
    }
  if (now - gLastRpcMs < 150)
    for (int y = 2; y < 6; ++y) px(10, y, 7);   // RPC activity
  px(12, (now / 125) % MX_H, 7);                // heartbeat
}

// --- RPCs ---------------------------------------------------------------------------------
static void served() {
  ++gRpcCount;
  gLastRpcMs = millis();
}

// ⚠ RPC integer PARAMETERS are signed on purpose. arduino-router 0.9.0 (image 558) re-encodes
// small non-negative ints (msgpack fixint 0..127) as a SIGNED type on the way through, and
// MsgPack's unpack into an unsigned C++ type rejects every signed encoding ("Wrong type
// parameter in position: 0"); 128+ arrives unsigned and worked, which hid it. Unpacking into
// a signed type accepts all integer encodings. Measured 2026-11-05; router 0.5.3 (image 424)
// passed fixints through unchanged. Return types are unaffected.
static int64_t rpcPing(int64_t n) {
  served();
  return n;
}

static bool rpcSetLed(bool on) {
  served();
  gLedOn = on;
  digitalWrite(LED_BUILTIN, (on == kLedActiveHigh) ? HIGH : LOW);
  return on;
}

static uint32_t rpcMcuMicros() {
  // Sample first, count second: the timestamp should be as close to the call as possible.
  uint32_t t = micros();
  served();
  return t;
}

static String rpcStatus() {
  served();
  String s = kBanner;
  s += " up_ms=";  s += millis();
  s += " rpcs=";   s += gRpcCount;
  s += " led=";    s += gLedOn ? "on" : "off";
  return s;
}

// --- setup / loop -------------------------------------------------------------------------
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, kLedActiveHigh ? LOW : HIGH);   // start off

  gMatrix.begin();
  gMatrix.setGrayscaleBits(3);
  drawFace(millis());
  gMatrix.draw(gPix);

  Bridge.begin();
  Monitor.begin();

  Bridge.provide_safe("ping", rpcPing);
  Bridge.provide_safe("set_led", rpcSetLed);
  Bridge.provide_safe("mcu_micros", rpcMcuMicros);
  Bridge.provide_safe("status", rpcStatus);

  Monitor.print(kBanner);
  Monitor.println(" online — RPCs: ping, set_led, mcu_micros, status");
}

void loop() {
  static uint32_t lastDraw = 0;
  uint32_t now = millis();
  if (now - lastDraw >= 40) {
    lastDraw = now;
    drawFace(now);
    gMatrix.draw(gPix);
  }
}
