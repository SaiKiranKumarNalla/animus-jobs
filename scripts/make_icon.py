"""Generate a simple app icon (.icns) using macOS sips/iconutil. Usage: make_icon.py OUT.icns"""
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path


def png(size):
    """Indigo rounded square with a white target ring, drawn pixel by pixel."""
    rows = []
    c, r_out, r_in, r_dot = size / 2, size * 0.30, size * 0.20, size * 0.08
    rad = size * 0.22
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx, dy = min(x, size - 1 - x), min(y, size - 1 - y)
            inside = not (dx < rad and dy < rad and (rad - dx) ** 2 + (rad - dy) ** 2 > rad ** 2)
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            if not inside:
                row += bytes([0, 0, 0, 0])
            elif d < r_dot or r_in < d < r_out:
                row += bytes([255, 255, 255, 255])
            else:
                row += bytes([79, 70, 229, 255])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", raw) + chunk(b"IEND", b"")


out = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as td:
    iconset = Path(td) / "icon.iconset"
    iconset.mkdir()
    for s in (16, 32, 128, 256, 512):
        (iconset / f"icon_{s}x{s}.png").write_bytes(png(s))
        (iconset / f"icon_{s}x{s}@2x.png").write_bytes(png(s * 2))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
