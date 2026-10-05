"""
Generates icon-192.png and icon-512.png for PWA.
Uses only Python stdlib - no Pillow needed.

Design: dark background · violet circle · white three-node network
"""

import math
import struct
import zlib
from pathlib import Path

BG     = (15,  17,  23)    # #0f1117
ACCENT = (124, 92, 255)    # #7c5cff
WHITE  = (255, 255, 255)


def dist_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def make_icon(size):
    cx = cy = size / 2
    # Circle radius stays inside the 80% maskable safe zone.
    cr = size * 0.38

    # Network: one hub in the middle, three nodes around it.
    hub   = (cx, cy)
    nodes = [(cx + cr * 0.55 * math.cos(a), cy + cr * 0.55 * math.sin(a))
             for a in (math.radians(-90), math.radians(30), math.radians(150))]
    line_w   = max(size * 0.022, 2)
    hub_r    = size * 0.060
    node_r   = size * 0.042

    raw = bytearray()
    for y in range(size):
        raw += b'\x00'
        for x in range(size):
            colour = BG
            if math.hypot(x - cx, y - cy) <= cr:
                colour = ACCENT
                on_line = any(dist_to_segment(x, y, *hub, *n) <= line_w for n in nodes)
                on_dot  = (math.hypot(x - hub[0], y - hub[1]) <= hub_r or
                           any(math.hypot(x - n[0], y - n[1]) <= node_r for n in nodes))
                if on_line or on_dot:
                    colour = WHITE
            raw += bytes(colour)

    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', compressed)
            + chunk(b'IEND', b''))


if __name__ == '__main__':
    icons_dir = Path(__file__).parent.parent / 'icons'
    icons_dir.mkdir(exist_ok=True)

    for size, name in [(192, 'icon-192.png'), (512, 'icon-512.png')]:
        data = make_icon(size)
        (icons_dir / name).write_bytes(data)
        print(f'Created {name}  ({size}x{size}, {len(data):,} bytes)')
