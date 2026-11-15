#!/usr/bin/env python3
"""Serve both eyes as a small website: live MJPEG streams, snapshots and a status page.

Runs on the UNO Q with plain python3 and Debian python3-opencv. It uses only the standard
library for HTTP, so nothing needs installing on a board with no network.

    python3 eye_server.py [--port 8080] [--size 1024x768] [--fps 15] [--quality 80]
                          [--rotate 0,0] [--eyes 1,2] [--test-pattern]

    /               page showing every eye
    /eye/N.mjpg     live stream of eye N (multipart JPEG; works in an <img> tag and in
                    cv2.VideoCapture("http://host:8080/eye/N.mjpg"))
    /eye/N.jpg      one frame of eye N
    /status         JSON: per-eye state, capture rate and frame count

Each eye has one capture thread. Frames are JPEG-encoded only while somebody is watching,
so an idle server costs capture time but no encoding. There is no login: anyone who can
reach the port can watch.

--test-pattern replaces the cameras with a generated image, to test the web side on a
machine that has no cameras.
"""
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from grab_frames import list_cameras, pipeline

BOUNDARY = "eyeframe"
WATCH_HOLD_S = 2.0      # keep encoding this long after the last viewer asked for a frame
REOPEN_DELAY_S = 2.0    # wait between attempts to open a camera that failed

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chameleon Eyes</title>
<style>
  body { margin: 0; background: #111; color: #ddd; font: 15px/1.4 system-ui, sans-serif; }
  header { padding: 10px 16px; }
  h1 { font-size: 18px; margin: 0; }
  main { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 8px 8px; }
  figure { flex: 1 1 320px; margin: 0; }
  img { width: 100%; display: block; background: #000; }
  figcaption { padding: 4px 2px; color: #999; font-size: 13px; }
</style>
</head>
<body>
<header><h1>Chameleon Eyes</h1></header>
<main>
@FIGURES@
</main>
<script>
async function poll() {
  try {
    const s = await (await fetch('/status')).json();
    for (const e of s.eyes) {
      const el = document.getElementById('cap' + e.eye);
      if (el) el.textContent = 'Eye ' + e.eye + ': ' + e.state + ', ' +
        e.width + 'x' + e.height + ', ' + e.capture_fps.toFixed(1) + ' fps captured';
    }
  } catch (err) { /* server gone; keep trying */ }
}
poll(); setInterval(poll, 2000);
</script>
</body>
</html>
"""

FIGURE = ('<figure><img src="/eye/%(n)d.mjpg" alt="Eye %(n)d">'
          '<figcaption id="cap%(n)d">Eye %(n)d</figcaption></figure>')


class Eye:
    """One camera: a capture thread that keeps the newest JPEG for any number of viewers."""

    def __init__(self, n, camera_id, width, height, rotate, quality, max_fps, test):
        self.n = n
        self.camera_id = camera_id
        self.width, self.height = width, height
        self.rotate = rotate
        self.quality = quality
        self.min_period = 1.0 / max_fps if max_fps > 0 else 0.0
        self.test = test
        self.cond = threading.Condition()
        self.jpeg = None
        self.seq = 0            # number of JPEGs published
        self.frames = 0         # number of frames captured
        self.capture_fps = 0.0
        self.state = "starting"
        self.watched_until = 0.0

    def start(self):
        threading.Thread(target=self._run, name=f"eye{self.n}", daemon=True).start()

    def watch(self):
        """Tell the capture thread that somebody wants frames."""
        self.watched_until = time.monotonic() + WATCH_HOLD_S

    def next_jpeg(self, after_seq, timeout=5.0):
        """Wait for a JPEG newer than after_seq. Returns (seq, bytes), or (after_seq, None)."""
        self.watch()
        with self.cond:
            self.cond.wait_for(lambda: self.seq > after_seq, timeout)
            if self.seq > after_seq:
                return self.seq, self.jpeg
        return after_seq, None

    def status(self):
        return {"eye": self.n, "camera": self.camera_id, "state": self.state,
                "width": self.width, "height": self.height,
                "capture_fps": round(self.capture_fps, 1), "frames": self.frames,
                "watched": time.monotonic() < self.watched_until}

    def _test_frame(self, i):
        img = np.zeros((self.height, self.width, 3), np.uint8)
        img[:] = (40, 30, 20)
        x = (i * 8) % self.width
        cv2.rectangle(img, (x, 0), (min(x + 40, self.width - 1), self.height - 1),
                      (0, 200, 255), -1)
        cv2.putText(img, f"eye {self.n}  frame {i}", (20, self.height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        time.sleep(1 / 30)
        return img

    def _run(self):
        while True:
            cap = None
            if not self.test:
                cap = cv2.VideoCapture(pipeline(self.camera_id, self.width, self.height),
                                       cv2.CAP_GSTREAMER)
                if not cap.isOpened():
                    self.state = "cannot open camera"
                    time.sleep(REOPEN_DELAY_S)
                    continue
            self.state = "running"
            self._capture(cap)
            if cap is not None:
                cap.release()
            self.state = "camera stopped, reopening"
            time.sleep(REOPEN_DELAY_S)

    def _capture(self, cap):
        last_pub = 0.0
        t_mark, n_mark = time.monotonic(), self.frames
        while True:
            if cap is None:
                frame = self._test_frame(self.frames)
            else:
                ok, frame = cap.read()
                if not ok:
                    return
            self.frames += 1
            now = time.monotonic()
            if now - t_mark >= 1.0:
                self.capture_fps = (self.frames - n_mark) / (now - t_mark)
                t_mark, n_mark = now, self.frames
            if now >= self.watched_until or now - last_pub < self.min_period:
                continue
            if self.rotate == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if not ok:
                continue
            last_pub = now
            with self.cond:
                self.jpeg = buf.tobytes()
                self.seq += 1
                self.cond.notify_all()


class Handler(BaseHTTPRequestHandler):
    eyes = {}   # eye number -> Eye, set by main()

    def log_message(self, fmt, *args):
        pass    # one line per request would flood the console during a stream

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _eye(self, name):
        """Eye for a path part like '2.mjpg', or None."""
        try:
            return self.eyes.get(int(name.split(".")[0]))
        except ValueError:
            return None

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/":
                figures = "\n".join(FIGURE % {"n": n} for n in sorted(self.eyes))
                self._send(200, "text/html; charset=utf-8",
                           PAGE.replace("@FIGURES@", figures).encode())
            elif path == "/status":
                body = json.dumps({"eyes": [self.eyes[n].status() for n in sorted(self.eyes)]})
                self._send(200, "application/json", body.encode())
            elif path.startswith("/eye/") and path.endswith(".mjpg"):
                eye = self._eye(path[5:])
                if eye is None:
                    self._send(404, "text/plain", b"no such eye\n")
                else:
                    self._stream(eye)
            elif path.startswith("/eye/") and path.endswith(".jpg"):
                eye = self._eye(path[5:])
                if eye is None:
                    self._send(404, "text/plain", b"no such eye\n")
                    return
                # after_seq = current seq, so the snapshot is a frame taken after the request
                _, jpeg = eye.next_jpeg(eye.seq)
                if jpeg is None:
                    self._send(503, "text/plain", f"eye {eye.n}: {eye.state}\n".encode())
                else:
                    self._send(200, "image/jpeg", jpeg)
            else:
                self._send(404, "text/plain", b"not found\n")
        except (BrokenPipeError, ConnectionError):
            pass    # the viewer went away

    def _stream(self, eye):
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        seq = eye.seq
        while True:
            seq, jpeg = eye.next_jpeg(seq)
            if jpeg is None:
                continue    # camera stalled; keep the connection and wait
            self.wfile.write(f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                             f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
            self.wfile.write(jpeg)
            self.wfile.write(b"\r\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--size", default="1024x768")
    ap.add_argument("--fps", type=float, default=15, help="most frames per second to send")
    ap.add_argument("--quality", type=int, default=80, help="JPEG quality, 1-100")
    ap.add_argument("--rotate", default="0",
                    help="0 or 180 per eye, comma separated; one value applies to all")
    ap.add_argument("--eyes", default="", help="eye numbers to serve, e.g. 1 or 1,2")
    ap.add_argument("--test-pattern", action="store_true")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))

    ids = ["test-1", "test-2"] if args.test_pattern else list_cameras()
    if not ids:
        print("[eyes] no cameras listed by `cam -l`")
        return 1
    wanted = [int(v) for v in args.eyes.split(",") if v] or list(range(1, len(ids) + 1))
    rotations = [int(v) for v in args.rotate.split(",")]
    if any(r not in (0, 180) for r in rotations):
        print("[eyes] --rotate takes 0 or 180")
        return 1

    for i, n in enumerate(wanted):
        if not 1 <= n <= len(ids):
            print(f"[eyes] there is no eye {n} (found {len(ids)})")
            return 1
        rotate = rotations[i] if i < len(rotations) else rotations[-1]
        eye = Eye(n, ids[n - 1], width, height, rotate, args.quality, args.fps,
                  args.test_pattern)
        Handler.eyes[n] = eye
        eye.start()
        print(f"[eyes] eye {n}: {ids[n - 1]}  rotate {rotate}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"[eyes] serving on http://{args.host}:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
