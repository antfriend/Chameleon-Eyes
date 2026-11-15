#!/usr/bin/env python3
"""Raw capture from both IMX219 eyes at the same time, without libcamera.

libcamera 0.4.0 on board image 558 routes BOTH cameras through msm_csid0 -> msm_vfe0_rdi0,
so the second camera to start fails with "Failed to setup link ... Device or resource busy"
(`cam -c1 -c2` fails the same way). The hardware has two of everything, so this module
sets the routes itself with media-ctl:

    eye 1: sensor on msm_csiphy0 -> msm_csid0 -> msm_vfe0_rdi0 -> msm_vfe0_video0
    eye 2: sensor on msm_csiphy1 -> msm_csid1 -> msm_vfe1_rdi0 -> msm_vfe1_video0

Eye numbers follow the carrier connector (the CSI PHY), not the order `cam -l` prints,
which changes between boots.

Frames are 8-bit Bayer (RGGB), 1640x1232, the sensor's 2x2-binned full field of view,
at 30 fps.
`v4l2-ctl` streams them to a pipe, and this module does what libcamera's software ISP did:
debayer, auto exposure, grey-world white balance and gamma. There is no colour matrix, so
colours are a little flat.

    setup([1, 2])            # once, before any camera streams
    cam = RawCamera(1); cam.open()
    raw = cam.read()         # None when the stream ends
    bgr = cam.to_bgr(raw, (820, 616))

Run it directly to save one JPEG per eye:  python3 eye_capture.py [--out DIR]
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

import cv2
import numpy as np

MEDIA = "/dev/media0"           # qcom-camss
SENSOR_W, SENSOR_H = 1640, 1232
MBUS_FORMAT = "SRGGB8_1X8"
PIXEL_FORMAT = "RGGB"
BLACK_LEVEL = 16                # IMX219 pedestal: 64 at 10 bits, so 16 at 8 bits

# The mode runs at 60 fps with the driver's default blanking of 475 lines. Stretching the
# blanking to 2182 lines halves that to 30 fps, which doubles the longest exposure and
# halves the data to process.
VERTICAL_BLANKING = 2182
MAX_EXPOSURE = SENSOR_H + VERTICAL_BLANKING - 4     # lines
MAX_GAIN_CODE = 232             # analogue gain = 256 / (256 - code), so 1x to 10.7x
AUTO_EVERY = 8                  # frames between exposure / white-balance updates
AE_TARGET = 45.0                # wanted mean of green above black, out of 239 (linear)

# eye number -> (csiphy, csid, vfe input, video node name)
ROUTES = {
    1: ("msm_csiphy0", "msm_csid0", "msm_vfe0_rdi0", "msm_vfe0_video0"),
    2: ("msm_csiphy1", "msm_csid1", "msm_vfe1_rdi0", "msm_vfe1_video0"),
}


def _media_ctl(*args):
    return subprocess.run(["media-ctl", "-d", MEDIA, *args], check=True,
                          capture_output=True, text=True).stdout


def _node(name):
    """/dev node of the V4L2 device or subdevice with this name."""
    for path in glob.glob("/sys/class/video4linux/*/name"):
        with open(path) as f:
            if f.read().strip() == name:
                return "/dev/" + path.split("/")[-2]
    raise RuntimeError(f"no V4L2 device named {name!r}")


def sensor_on(csiphy):
    """Name of the sensor entity wired to a CSI PHY, e.g. 'imx219 2-0010'."""
    block = re.search(rf"- entity \d+: {csiphy} .*?(?=\n- entity|\Z)", _media_ctl("-p"), re.S)
    found = re.search(r'<- "([^"]+)":0', block.group(0)) if block else None
    if not found:
        raise RuntimeError(f"no sensor found on {csiphy}")
    return found.group(1)


def setup(eyes=(1, 2)):
    """Give each eye its own route and set the format along it. Nothing may be streaming."""
    _media_ctl("-r")
    for n in eyes:
        csiphy, csid, rdi, _ = ROUTES[n]
        _media_ctl("-l", f'"{csiphy}":1->"{csid}":0[1]')
        _media_ctl("-l", f'"{csid}":1->"{rdi}":0[1]')
        for entity in (sensor_on(csiphy), csiphy, csid, rdi):
            _media_ctl("-V", f'"{entity}":0[fmt:{MBUS_FORMAT}/{SENSOR_W}x{SENSOR_H} field:none]')


class RawCamera:
    """One eye. read() returns the newest raw Bayer frame; to_bgr() makes it viewable."""

    def __init__(self, eye):
        csiphy, _, _, video = ROUTES[eye]
        self.eye = eye
        self.sensor = sensor_on(csiphy)
        self.sensor_dev = _node(self.sensor)
        self.video_dev = _node(video)
        self.proc = None
        self.raw = np.empty((SENSOR_H, SENSOR_W), np.uint8)
        self.count = 0
        self.product = 1600.0       # exposure lines x analogue gain
        self.exposure, self.gain = 0, 1.0
        self.wb_red, self.wb_blue = 1.0, 1.0
        self._build_lut()

    def open(self):
        # Blanking first: it sets the range the exposure control accepts.
        subprocess.run(["v4l2-ctl", "-d", self.sensor_dev, "-c",
                        f"vertical_blanking={VERTICAL_BLANKING}"], capture_output=True)
        self._apply_exposure()
        self.proc = subprocess.Popen(
            ["v4l2-ctl", "-d", self.video_dev,
             f"--set-fmt-video=width={SENSOR_W},height={SENSOR_H},pixelformat={PIXEL_FORMAT}",
             "--stream-mmap", "--stream-to=-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

    def close(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            self.proc = None

    def read(self):
        """Next frame as an (H, W) uint8 Bayer array, or None if the stream ended.

        The array is reused by the following read(), so finish with it first.
        """
        view = memoryview(self.raw).cast("B")
        got = 0
        while got < len(view):
            n = self.proc.stdout.readinto(view[got:])
            if not n:
                return None
            got += n
        self.count += 1
        if self.count % AUTO_EVERY == 0:
            self._auto()
        return self.raw

    def to_bgr(self, raw, size):
        """Debayer, resize to (width, height), then white balance and gamma."""
        # OpenCV names Bayer patterns by the 2x2 block one pixel in, so RGGB data is "BG".
        bgr = cv2.cvtColor(raw, cv2.COLOR_BayerBG2BGR)
        if size != (SENSOR_W, SENSOR_H):
            bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
        return cv2.LUT(bgr, self.lut)

    def info(self):
        return {"sensor": self.sensor, "exposure_lines": self.exposure,
                "gain": round(self.gain, 2),
                "wb_red": round(self.wb_red, 2), "wb_blue": round(self.wb_blue, 2)}

    def _auto(self):
        raw = self.raw
        red = float(raw[0::8, 0::8].mean()) - BLACK_LEVEL
        green = max(float(raw[0::8, 1::8].mean()) - BLACK_LEVEL, 1.0)
        blue = float(raw[1::8, 1::8].mean()) - BLACK_LEVEL

        # Exposure: move part of the way to the target, and ignore small errors.
        ratio = min(max((AE_TARGET / green) ** 0.7, 0.5), 2.0)
        if abs(ratio - 1.0) > 0.08:
            top = MAX_EXPOSURE * 256.0 / (256 - MAX_GAIN_CODE)
            product = min(max(self.product * ratio, 4.0), top)
            if product != self.product:
                self.product = product
                self._apply_exposure()

        # Grey-world white balance: scale red and blue so their means match green.
        if red > 1.0 and blue > 1.0:
            self.wb_red += 0.2 * (min(max(green / red, 0.5), 4.0) - self.wb_red)
            self.wb_blue += 0.2 * (min(max(green / blue, 0.5), 4.0) - self.wb_blue)
            self._build_lut()

    def _apply_exposure(self):
        """Use exposure time first, then analogue gain, to reach self.product."""
        self.exposure = int(min(MAX_EXPOSURE, max(4, round(self.product))))
        gain = max(self.product / self.exposure, 1.0)
        code = min(max(int(round(256 - 256 / gain)), 0), MAX_GAIN_CODE)
        self.gain = 256.0 / (256 - code)
        subprocess.run(["v4l2-ctl", "-d", self.sensor_dev, "-c",
                        f"exposure={self.exposure},analogue_gain={code}"],
                       capture_output=True)

    def _build_lut(self):
        linear = np.clip(np.arange(256) - BLACK_LEVEL, 0, None) / (255.0 - BLACK_LEVEL)
        channels = [255.0 * np.clip(linear * g, 0, 1) ** (1 / 2.2)
                    for g in (self.wb_blue, 1.0, self.wb_red)]
        self.lut = np.stack(channels, axis=-1).reshape(256, 1, 3).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=".")
    ap.add_argument("--frames", type=int, default=60, help="frames to read before saving")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    setup()
    cams = [RawCamera(n) for n in sorted(ROUTES)]
    for cam in cams:
        cam.open()
    t0 = time.monotonic()
    failed = 0
    for i in range(args.frames):
        for cam in cams:
            if cam.read() is None:
                print(f"[eye{cam.eye}] stream ended at frame {i}")
                failed = 1
        if failed:
            break
    fps = args.frames / (time.monotonic() - t0)
    for cam in cams:
        if not failed:
            path = os.path.join(args.out, f"eye{cam.eye}.jpg")
            cv2.imwrite(path, cam.to_bgr(cam.raw, (SENSOR_W // 2, SENSOR_H // 2)))
            print(f"[eye{cam.eye}] {fps:.1f} fps with both eyes running  -> {path}  {cam.info()}")
        cam.close()
    return failed


if __name__ == "__main__":
    sys.exit(main())
