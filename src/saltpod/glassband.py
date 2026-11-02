# saltglass:band v0.5.1 @91f89d6 sha256=94e2309f5f4c16bd9b559d31616457f6aa9bc5f93e3ee285c78bbbe1941a5116
#!/usr/bin/env python3
"""saltglass — band.py: the luminance band.

The ground of a page is the content's own picture, blurred, under a scrim of
the ground colour. A bright picture after a dark one would flash. The band
prevents that: for every picture, the host's server measures the mean colour
and computes the scrim alpha that keeps the composite ground at or under a
luminance ceiling. The page never measures colour; it looks the number up.

The light appearance needs the band the other way round. Its scrim is the light
ground, and a dark picture under it would sink the page below the point where
dark ink reads; so for a light page the scrim is the smallest alpha that keeps
the composite at or OVER a floor, Y_MIN. Same contract, {y, scrim}; the host
says which appearance it measures for.

Pure, stdlib. The only dependency is ffmpeg, and only for mean_rgb() (decode +
reduce in RGB; the average itself is exact, here).

The arithmetic, which any check must match exactly:

  sRGB mean of the image, r g b in 0..255 (floats: the true average of the
                       pixels, never a scaler's single pixel).
  composite, in sRGB:  c = (1 - a) * mean + a * ground
  relative luminance:  lin(v) = v/255 <= .03928 ? v/255/12.92 : ((v/255 + .055)/1.055) ** 2.4
                       Y = .2126 lin(r) + .7152 lin(g) + .0722 lin(b)
  scrim_for(mean):     .30 if the composite at .30 is already under the ceiling,
                       .85 if the composite at .85 is still over it,
                       else bisect a in [.30, .85] 18 times for Y = Y_MAX and
                       return the upper bound rounded UP to two places, so the
                       rounding never breaches the ceiling.
  scrim_for(mean, appearance='light'):
                       the same with the light ground and the floor: .30 if the
                       composite at .30 is already at or over Y_MIN, .85 if the
                       composite at .85 is still under it, else bisect for
                       Y = Y_MIN and return the upper bound rounded up.

Usage:  python3 band.py [--appearance dark|light] [--ground '#rrggbb'] IMAGE...
        prints one JSON object per line: {"path": ..., "mean": [r, g, b], "y": ..., "scrim": ...}
        --ground passes the host's own ground (the default is the appearance's).
"""
import json
import math
import subprocess
import sys

GROUND = (20, 29, 41)   # the default ground, #141d29, Y = .0119
LIGHT_GROUND = (243, 245, 248)   # the light appearance's ground, #f3f5f8, Y = .911
Y_MAX = .05             # the dark ground's ceiling in relative luminance
Y_MIN = .30             # the light ground's floor: dark ink (#141d29) reads 5.66:1 on it
SCRIM_MIN = .30
SCRIM_MAX = .85
BISECT_STEPS = 18


class MeasureError(Exception):
    """ffmpeg is missing, or the image cannot be read."""


def linear(v):
    """One sRGB channel 0..255 to linear light 0..1 (the WCAG 2 curve)."""
    v = v / 255.0
    if v <= .03928:
        return v / 12.92
    return ((v + .055) / 1.055) ** 2.4


def luminance(rgb):
    """Relative luminance Y of an sRGB triple."""
    r, g, b = rgb
    return .2126 * linear(r) + .7152 * linear(g) + .0722 * linear(b)


def composite(mean, a, ground=GROUND):
    """The ground colour at alpha a over the mean, mixed in sRGB."""
    return tuple((1 - a) * mean[i] + a * ground[i] for i in range(3))


def _round_up(a):
    """Two places, upwards: the bisection's upper bound always satisfies the band,
    and a bound rounded down can fall back outside it."""
    return math.ceil(round(a * 100, 9)) / 100


def scrim_for(mean, ground=None, appearance='dark'):
    """The smallest scrim alpha in [SCRIM_MIN, SCRIM_MAX] that keeps the
    composite ground at or under Y_MAX (dark), or at or over Y_MIN (light),
    to two places, rounded towards the safe side."""
    if appearance not in ('dark', 'light'):
        raise ValueError('appearance is dark or light, not %r' % appearance)
    light = appearance == 'light'
    if ground is None:
        ground = LIGHT_GROUND if light else GROUND

    def ok(a):
        y = luminance(composite(mean, a, ground))
        return y >= Y_MIN if light else y <= Y_MAX

    if ok(SCRIM_MIN):
        return SCRIM_MIN
    if not ok(SCRIM_MAX):
        return SCRIM_MAX
    lo, hi = SCRIM_MIN, SCRIM_MAX
    for _ in range(BISECT_STEPS):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return min(SCRIM_MAX, _round_up(hi))


def parse_hex(text):
    """'#rrggbb' to (r, g, b) in 0..255."""
    h = text.strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6 or any(c not in '0123456789abcdefABCDEF' for c in h):
        raise ValueError('not a #rrggbb colour: %r' % text)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


MEAN_SIDE = 256         # mean_rgb() reduces to at most this many pixels per side, in RGB


def mean_rgb(path, ffmpeg='ffmpeg'):
    """The sRGB mean of an image: ffmpeg decodes it, converts to rgb24 FIRST
    and only then reduces it with the area filter to at most MEAN_SIDE px a
    side (never enlarged), and the exact average of those pixels is taken here.

    Not `scale=1:1`: swscale's area filter at that ratio is no box mean
    (205 against a true 182 on one photo), and scaling before the RGB
    conversion (in YUV) moves the mean by up to a level. Converted first and
    reduced to 256 px, the mean is within .05 of the full-frame decode's
    (measured on a 512 preview and a 102 MP JPEG). Returns floats, two places."""
    vf = ("format=rgb24,scale=w='min(%d,iw)':h='min(%d,ih)':force_original_aspect_ratio=decrease:flags=area"
          % (MEAN_SIDE, MEAN_SIDE))
    cmd = [ffmpeg, '-v', 'quiet', '-i', path, '-vf', vf, '-frames:v', '1',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout
    except (OSError, FileNotFoundError) as e:
        raise MeasureError('ffmpeg not available (%s): %s' % (ffmpeg, e))
    n = len(out) // 3
    if n < 1:
        raise MeasureError('unreadable image: %s' % path)
    return tuple(round(sum(out[i::3]) / n, 2) for i in range(3))


def measure(path, ffmpeg='ffmpeg', ground=None, appearance='dark'):
    """{'mean': [r, g, b], 'y': Y of the mean, 'scrim': scrim_for(mean)}."""
    mean = mean_rgb(path, ffmpeg)
    return {'mean': list(mean), 'y': round(luminance(mean), 4), 'scrim': scrim_for(mean, ground, appearance)}


def parse_args(argv):
    """(appearance, ground or None, [paths]) from the command line."""
    appearance, ground, paths = 'dark', None, []
    it = iter(argv)
    for a in it:
        if a == '--appearance':
            appearance = next(it, '')
            if appearance not in ('dark', 'light'):
                raise ValueError('--appearance is dark or light')
        elif a == '--ground':
            ground = parse_hex(next(it, ''))
        else:
            paths.append(a)
    return appearance, ground, paths


def main(argv):
    usage = "usage: band.py [--appearance dark|light] [--ground '#rrggbb'] IMAGE...\n"
    if not argv or argv[0] in ('-h', '--help'):
        sys.stderr.write(usage)
        return 2
    try:
        appearance, ground, paths = parse_args(argv)
    except ValueError as e:
        sys.stderr.write('%s\n%s' % (e, usage))
        return 2
    status = 0
    for path in paths:
        try:
            m = measure(path, ground=ground, appearance=appearance)
        except MeasureError as e:
            sys.stderr.write('%s: %s\n' % (path, e))
            status = 1
            continue
        m = dict(path=path, **m)
        sys.stdout.write(json.dumps(m) + '\n')
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
# /saltglass:band
