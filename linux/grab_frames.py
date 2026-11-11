#!/usr/bin/env python3
"""Grab one frame from each IMX219 eye through OpenCV and save it as a JPEG.

Runs on the UNO Q (plain python3, Debian python3-opencv with GStreamer). Each camera is
opened through libcamera's GStreamer source, because the raw V4L2 nodes give Bayer data
that needs the media pipeline set up by hand.

    python3 grab_frames.py [--size 1024x768] [--warmup 30] [--out DIR]

Prints one line per camera: frame shape, mean brightness, and the frame rate seen while
warming up (time.monotonic, since the board's wall clock is not trustworthy).
"""
import argparse
import os
import subprocess
import sys
import time

import cv2


def list_cameras():
    """libcamera camera ids, in `cam -l` order (index 1, 2, ...)."""
    out = subprocess.run(["cam", "-l"], capture_output=True, text=True).stdout
    ids = []
    for line in out.splitlines():
        # e.g.  1: 'imx219' (/base/soc@0/cci@5c1b000/i2c-bus@1/sensor@10)
        if ": '" in line and line.rstrip().endswith(")"):
            ids.append(line[line.rindex("(") + 1:-1].strip())
    return ids


def pipeline(camera_id, width, height):
    return (
        f'libcamerasrc camera-name="{camera_id}" ! '
        f"video/x-raw,width={width},height={height} ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def grab(camera_id, width, height, warmup):
    cap = cv2.VideoCapture(pipeline(camera_id, width, height), cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        return None, 0.0
    frame = None
    t0 = time.monotonic()
    got = 0
    # Let auto-exposure and white balance settle before keeping a frame.
    for _ in range(warmup):
        ok, f = cap.read()
        if not ok:
            break
        frame = f
        got += 1
    dt = time.monotonic() - t0
    cap.release()
    return frame, (got / dt if dt > 0 else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1024x768")
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))

    ids = list_cameras()
    if not ids:
        print("[grab] no cameras listed by `cam -l`")
        return 1
    os.makedirs(args.out, exist_ok=True)
    failed = 0
    for n, cam_id in enumerate(ids, start=1):
        frame, fps = grab(cam_id, width, height, args.warmup)
        if frame is None:
            print(f"[cam{n}] FAILED to get a frame  ({cam_id})")
            failed += 1
            continue
        path = os.path.join(args.out, f"cam{n}.jpg")
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        h, w = frame.shape[:2]
        print(f"[cam{n}] {w}x{h}  mean={frame.mean():.1f}  "
              f"warmup={fps:.1f} fps  -> {path}  ({cam_id})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
