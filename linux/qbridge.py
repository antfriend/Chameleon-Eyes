"""qbridge.py — a dependency-free Bridge client for the UNO Q's Linux side.

App Lab apps get `from arduino.app_utils import Bridge`, but that package only exists
inside App Lab's containers; the board's system python3 has neither it nor `msgpack`.
This module talks to the same thing App Lab does — `arduino-router`, a msgpack-RPC
server on the Unix socket /var/run/arduino-router.sock — so scripts in linux/ run with
plain `python3` over adb, the way the robot_team boards are driven from a cable.

    from qbridge import Bridge
    Bridge.call("ping", 7)   # -> 7, served by Bridge.provide_safe("ping", ...) on the MCU

Two ways in, chosen automatically:
  ON THE BOARD   the Unix socket directly.
  ON THE PC      (Windows has no AF_UNIX path to the board) qbridge runs
                 `adb forward tcp:5775 localfilesystem:/var/run/arduino-router.sock`
                 and connects to 127.0.0.1:5775. Same RPCs, but every call also crosses
                 USB + adbd, so `Bridge.remote` is True and timings are NOT the board's.

Wire format (msgpack-RPC): request [0, msgid, method, params],
response [1, msgid, error, result], notification [2, method, params].
Only the msgpack subset RPC needs is implemented: nil, bool, int, float, str, bin,
array, map.
"""
import glob
import os
import shutil
import socket
import struct
import subprocess

SOCKET_PATH = os.environ.get("ARDUINO_ROUTER_SOCK", "/var/run/arduino-router.sock")
FORWARD_PORT = int(os.environ.get("ARDUINO_ROUTER_TCP", "5775"))


def find_adb():
    """$ADB, else the adb the arduino:zephyr core installed, else adb on PATH."""
    if os.environ.get("ADB"):
        return os.environ["ADB"]
    local = os.environ.get("LOCALAPPDATA", "")
    hits = sorted(glob.glob(os.path.join(local, "Arduino15", "packages", "arduino",
                                         "tools", "adb", "*", "adb*")))
    hits = [h for h in hits if os.path.basename(h).lower() in ("adb", "adb.exe")]
    return hits[-1] if hits else shutil.which("adb")


def on_board() -> bool:
    return hasattr(socket, "AF_UNIX") and os.path.exists(SOCKET_PATH)


# --- minimal msgpack ----------------------------------------------------------------------
def pack(o) -> bytes:
    if o is None:
        return b"\xc0"
    if o is True:
        return b"\xc3"
    if o is False:
        return b"\xc2"
    if isinstance(o, int):
        if 0 <= o < 0x80:
            return bytes([o])
        if -32 <= o < 0:
            return struct.pack("b", o)
        if o >= 0:
            for code, fmt, lim in ((0xcc, ">B", 1 << 8), (0xcd, ">H", 1 << 16),
                                   (0xce, ">I", 1 << 32), (0xcf, ">Q", 1 << 64)):
                if o < lim:
                    return bytes([code]) + struct.pack(fmt, o)
        for code, fmt, lim in ((0xd0, ">b", 1 << 7), (0xd1, ">h", 1 << 15),
                               (0xd2, ">i", 1 << 31), (0xd3, ">q", 1 << 63)):
            if -lim <= o:
                return bytes([code]) + struct.pack(fmt, o)
        raise OverflowError(o)
    if isinstance(o, float):
        return b"\xcb" + struct.pack(">d", o)
    if isinstance(o, str):
        b = o.encode("utf-8")
        n = len(b)
        if n < 32:
            return bytes([0xa0 | n]) + b
        if n < 1 << 8:
            return b"\xd9" + struct.pack(">B", n) + b
        if n < 1 << 16:
            return b"\xda" + struct.pack(">H", n) + b
        return b"\xdb" + struct.pack(">I", n) + b
    if isinstance(o, (bytes, bytearray)):
        n = len(o)
        if n < 1 << 8:
            return b"\xc4" + struct.pack(">B", n) + bytes(o)
        if n < 1 << 16:
            return b"\xc5" + struct.pack(">H", n) + bytes(o)
        return b"\xc6" + struct.pack(">I", n) + bytes(o)
    if isinstance(o, (list, tuple)):
        n = len(o)
        head = bytes([0x90 | n]) if n < 16 else (
            b"\xdc" + struct.pack(">H", n) if n < 1 << 16 else b"\xdd" + struct.pack(">I", n))
        return head + b"".join(pack(x) for x in o)
    if isinstance(o, dict):
        n = len(o)
        head = bytes([0x80 | n]) if n < 16 else (
            b"\xde" + struct.pack(">H", n) if n < 1 << 16 else b"\xdf" + struct.pack(">I", n))
        return head + b"".join(pack(k) + pack(v) for k, v in o.items())
    raise TypeError(f"cannot msgpack {type(o).__name__}")


class _NeedMore(Exception):
    pass


def unpack(buf: bytes, i: int = 0):
    """Decode one object at buf[i:]; return (obj, next_i). Raises _NeedMore if short."""
    def take(n):
        nonlocal i
        if i + n > len(buf):
            raise _NeedMore
        b = buf[i:i + n]
        i += n
        return b

    def u(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))[0]

    def seq(n):
        nonlocal i
        out = []
        for _ in range(n):
            v, i = unpack(buf, i)
            out.append(v)
        return out

    def mp(n):
        nonlocal i
        out = {}
        for _ in range(n):
            k, i = unpack(buf, i)
            v, i = unpack(buf, i)
            out[k if not isinstance(k, list) else tuple(k)] = v
        return out

    c = take(1)[0]
    if c < 0x80:
        return c, i
    if c >= 0xe0:
        return c - 0x100, i
    if 0x80 <= c <= 0x8f:
        return mp(c & 0x0f), i
    if 0x90 <= c <= 0x9f:
        return seq(c & 0x0f), i
    if 0xa0 <= c <= 0xbf:
        return take(c & 0x1f).decode("utf-8", "replace"), i
    simple = {0xc0: None, 0xc2: False, 0xc3: True}
    if c in simple:
        return simple[c], i
    if c in (0xc4, 0xc5, 0xc6):
        return take(u({0xc4: ">B", 0xc5: ">H", 0xc6: ">I"}[c])), i
    if c == 0xca:
        return u(">f"), i
    if c == 0xcb:
        return u(">d"), i
    ints = {0xcc: ">B", 0xcd: ">H", 0xce: ">I", 0xcf: ">Q",
            0xd0: ">b", 0xd1: ">h", 0xd2: ">i", 0xd3: ">q"}
    if c in ints:
        return u(ints[c]), i
    if c in (0xd9, 0xda, 0xdb):
        return take(u({0xd9: ">B", 0xda: ">H", 0xdb: ">I"}[c])).decode("utf-8", "replace"), i
    if c in (0xdc, 0xdd):
        return seq(u(">H" if c == 0xdc else ">I")), i
    if c in (0xde, 0xdf):
        return mp(u(">H" if c == 0xde else ">I")), i
    raise ValueError(f"unsupported msgpack type 0x{c:02x}")


# --- RPC client -----------------------------------------------------------------------------
class BridgeError(RuntimeError):
    pass


class _Bridge:
    def __init__(self, path=SOCKET_PATH, timeout=5.0):
        self._path = path
        self._timeout = timeout
        self._sock = None
        self._buf = b""
        self._msgid = 0

    remote = False   # True when calls go PC -> adb -> board (timings include USB)

    def _connect(self):
        if self._sock is not None:
            return
        if on_board():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(self._timeout)
            s.connect(self._path)
            self._sock = s
            return
        adb = find_adb()
        if not adb:
            raise BridgeError("not on the UNO Q and no adb found: set $ADB, or install the "
                              "arduino:zephyr core (it ships adb)")
        r = subprocess.run([adb, "forward", f"tcp:{FORWARD_PORT}",
                            f"localfilesystem:{self._path}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise BridgeError(f"adb forward failed (is the UNO Q plugged in? `adb devices`): "
                              f"{(r.stderr or r.stdout).strip()}")
        self._sock = socket.create_connection(("127.0.0.1", FORWARD_PORT), timeout=self._timeout)
        self.remote = True

    def _read_msg(self):
        while True:
            try:
                obj, n = unpack(self._buf)
                self._buf = self._buf[n:]
                return obj
            except _NeedMore:
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise BridgeError("router closed the connection")
                self._buf += chunk

    def call(self, method, *params):
        """Blocking RPC; returns the result or raises BridgeError."""
        self._connect()
        self._msgid = (self._msgid + 1) & 0xFFFFFFFF
        msgid = self._msgid
        self._sock.sendall(pack([0, msgid, method, list(params)]))
        while True:
            msg = self._read_msg()
            if isinstance(msg, list) and len(msg) == 4 and msg[0] == 1 and msg[1] == msgid:
                if msg[2] is not None:
                    raise BridgeError(f"{method}: {msg[2]}")
                return msg[3]
            # anything else (notifications, stray responses) is not ours; skip it

    def notify(self, method, *params):
        self._connect()
        self._sock.sendall(pack([2, method, list(params)]))

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None


Bridge = _Bridge()
