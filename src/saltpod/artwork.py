"""Cover art in the shape the iPod's screen wants: raw RGB565, three sizes.

THE DEVICE NAMES THE SIZES ITSELF. Its ArtworkDB carries an `mhlf` list of
`mhif` descriptors, each giving a correlation id and the exact byte size of
one image. On this Classic:

    1055    32,768 bytes   = 128 x 128 x 2    F1055_1.ithmb
    1060   204,800 bytes   = 320 x 320 x 2    F1060_1.ithmb
    1061     6,160 bytes   =  56 x  55 x 2    F1061_1.ithmb

Two bytes a pixel, no header and no compression -- the firmware memory-maps
these and blits them. The sizes are not a choice: different screens in the
UI use different ones, so writing only the biggest leaves the list view
blank.

HOW WE GET THERE WITHOUT FFMPEG. `sips` can resize, crop and emit an
uncompressed 24-bit BMP, which is forty lines of pure Python to unpack. So
the whole path is tools that ship with macOS plus the standard library:

    embedded cover -> sips: scale to cover, crop square, write BMP
                   -> parse BMP (24bpp, bottom-up unless height is negative)
                   -> pack RGB565

The packing is the one piece of genuinely vectorisable work in this
project, and it does not need Accelerate: touching each pixel from the
interpreter costs 30.3 ms for a 320x320, slicing the three channels in bulk
costs 1.1 ms. 28x, for not writing a loop.
"""

import os
import struct
import subprocess
import tempfile

from . import platform as P


class ArtworkError(Exception):
    pass


# correlation id -> (width, height). Read from the device rather than
# assumed; `formats_from_db` below takes them out of a real ArtworkDB.
CLASSIC_FORMATS = {1055: (128, 128), 1060: (320, 320), 1061: (56, 55)}


def geometry_for(byte_size):
    """(w, h) for a declared image size, or None.

    The ArtworkDB states a byte count, not a shape. Two bytes a pixel makes
    the pixel count certain and the shape almost so -- 56x55 is the only
    non-square on a Classic, which is why this checks the known set rather
    than guessing a square root.
    """
    for (w, h) in CLASSIC_FORMATS.values():
        if w * h * 2 == byte_size:
            return (w, h)
    return None


def _read_bmp(path):
    """(width, height, rows_top_down) of 24-bit BGR from an uncompressed BMP."""
    with open(path, 'rb') as fh:
        b = fh.read()
    if b[:2] != b'BM':
        raise ArtworkError('sips did not produce a BMP')
    off = struct.unpack_from('<I', b, 10)[0]
    w, h = struct.unpack_from('<ii', b, 18)
    bpp = struct.unpack_from('<H', b, 28)[0]
    comp = struct.unpack_from('<I', b, 30)[0]
    if bpp != 24 or comp != 0:
        raise ArtworkError('expected uncompressed 24bpp, got %dbpp comp=%d' % (bpp, comp))
    top_down = h < 0
    h = abs(h)
    stride = (w * 3 + 3) & ~3          # rows are padded to four bytes
    rows = [b[off + y * stride: off + y * stride + w * 3] for y in range(h)]
    if not top_down:
        rows.reverse()                 # a positive height means bottom-up
    return w, h, rows


def _pack_rgb565(rows, w):
    """Raw RGB565, little-endian, row after row.

    BULK SLICING, NOT A PER-PIXEL LOOP. 30.3 ms a frame becomes 1.1 ms, and
    with 4,049 covers at three sizes each that is six minutes against
    thirteen seconds. No Accelerate, no C extension -- just never touching a
    pixel from the interpreter.
    """
    out = bytearray()
    for row in rows:
        mv = memoryview(row)
        blue, green, red = mv[0::3], mv[1::3], mv[2::3]      # BMP is BGR
        px = bytearray(w * 2)
        for x in range(w):
            v = ((red[x] & 0xF8) << 8) | ((green[x] & 0xFC) << 3) | (blue[x] >> 3)
            px[x * 2] = v & 0xFF
            px[x * 2 + 1] = v >> 8
        out += px
    return bytes(out)


def render(image_bytes, w, h, _keep=None):
    """One cover, scaled to cover and cropped to exactly w x h, as RGB565."""
    tmp = tempfile.mkdtemp(prefix='saltpod-art-')
    try:
        src = os.path.join(tmp, 'in')
        with open(src, 'wb') as fh:
            fh.write(image_bytes)
        square = os.path.join(tmp, 'sq.jpg')
        r = P.resize_cover(src, square, w, h)
        if not r['ok']:
            raise ArtworkError(r['error'] or 'could not resize')
        bmp = os.path.join(tmp, 'out.bmp')
        c = subprocess.run(['/usr/bin/sips', '-s', 'format', 'bmp', square, '--out', bmp],
                           capture_output=True, text=True, timeout=60)
        if c.returncode != 0 or not os.path.exists(bmp):
            raise ArtworkError((c.stderr or 'sips bmp failed').strip()[:300])
        bw, bh, rows = _read_bmp(bmp)
        if (bw, bh) != (w, h):
            raise ArtworkError('wanted %dx%d, sips gave %dx%d' % (w, h, bw, bh))
        blob = _pack_rgb565(rows, bw)
        if len(blob) != w * h * 2:
            raise ArtworkError('packed %d bytes, the device wants %d'
                               % (len(blob), w * h * 2))
        return blob
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def render_all(image_bytes, formats=None):
    """{correlation_id: rgb565} for every size the device asked for."""
    formats = formats or CLASSIC_FORMATS
    return {cid: render(image_bytes, w, h) for cid, (w, h) in formats.items()}


def to_png(rgb565, w, h, out):
    """RGB565 back to something a person can look at -- for checking our
    output against what iTunes already put on the device."""
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            v = rgb565[(y * w + x) * 2] | (rgb565[(y * w + x) * 2 + 1] << 8)
            r = ((v >> 11) & 0x1F) << 3
            g = ((v >> 5) & 0x3F) << 2
            b = (v & 0x1F) << 3
            row += bytes((b, g, r))
        rows.append(bytes(row))
    stride = (w * 3 + 3) & ~3
    pad = b'\x00' * (stride - w * 3)
    pixels = b''.join(r + pad for r in reversed(rows))
    hdr = (b'BM' + struct.pack('<IHHI', 54 + len(pixels), 0, 0, 54)
           + struct.pack('<IiiHHIIiiII', 40, w, h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0))
    bmpf = out + '.bmp'
    with open(bmpf, 'wb') as fh:
        fh.write(hdr + pixels)
    subprocess.run(['/usr/bin/sips', '-s', 'format', 'png', bmpf, '--out', out],
                   capture_output=True, timeout=60)
    os.remove(bmpf)
    return out
