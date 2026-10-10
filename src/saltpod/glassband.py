# vendored from saltglass @cc154d31ce49da64e6729d4601b8c99bde5d7249; edit upstream, re-run scripts/vendor_glass.py
"""saltglass — band.py: the luminance band.

The ground of a page is the content's own picture, blurred, under a scrim of
the ground colour. A bright picture after a dark one would flash. The band
prevents that: for every picture, the host's server measures the mean colour
and computes the scrim alpha that keeps the composite ground at or under a
luminance ceiling. The page never measures colour; it looks the number up.

Pure, stdlib. The only dependency is ffmpeg, and only for mean_rgb().

The arithmetic, which any check must match exactly:

  sRGB mean of the image, r g b in 0..255.
  composite, in sRGB:  c = (1 - a) * mean + a * ground
  relative luminance:  lin(v) = v/255 <= .03928 ? v/255/12.92 : ((v/255 + .055)/1.055) ** 2.4
                       Y = .2126 lin(r) + .7152 lin(g) + .0722 lin(b)
  scrim_for(mean):     .30 if the composite at .30 is already under the ceiling,
                       .85 if the composite at .85 is still over it,
                       else bisect a in [.30, .85] 18 times for Y = Y_MAX and
                       return the upper bound rounded to two places.

Usage:  python3 band.py IMAGE...   prints one JSON object per line:
        {"path": ..., "mean": [r, g, b], "y": ..., "scrim": ...}
"""
import json
import subprocess
import sys

GROUND = (20, 29, 41)   # the default ground, #141d29, Y = .0119
Y_MAX = .05             # the ground's ceiling in relative luminance
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


def scrim_for(mean, ground=GROUND):
    """The smallest scrim alpha in [SCRIM_MIN, SCRIM_MAX] that keeps the
    composite ground at or under Y_MAX, to two places."""
    if luminance(composite(mean, SCRIM_MIN, ground)) <= Y_MAX:
        return SCRIM_MIN
    if luminance(composite(mean, SCRIM_MAX, ground)) >= Y_MAX:
        return SCRIM_MAX
    lo, hi = SCRIM_MIN, SCRIM_MAX
    for _ in range(BISECT_STEPS):
        mid = (lo + hi) / 2
        if luminance(composite(mean, mid, ground)) > Y_MAX:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)


def mean_rgb(path, ffmpeg='ffmpeg'):
    """The sRGB mean of an image, in one ffmpeg call: the picture scaled to a
    single pixel with the area filter (a true box mean; the default bicubic
    scaler is position-dependent at this ratio) and written out as three raw
    bytes."""
    cmd = [ffmpeg, '-v', 'quiet', '-i', path, '-vf', 'scale=1:1:flags=area',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout
    except (OSError, FileNotFoundError) as e:
        raise MeasureError('ffmpeg not available (%s): %s' % (ffmpeg, e))
    if len(out) < 3:
        raise MeasureError('unreadable image: %s' % path)
    return (out[0], out[1], out[2])


def measure(path, ffmpeg='ffmpeg', ground=GROUND):
    """{'mean': [r, g, b], 'y': Y of the mean, 'scrim': scrim_for(mean)}."""
    mean = mean_rgb(path, ffmpeg)
    return {'mean': list(mean), 'y': round(luminance(mean), 4), 'scrim': scrim_for(mean, ground)}


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        sys.stderr.write('usage: band.py IMAGE...\n')
        return 2
    status = 0
    for path in argv:
        try:
            m = measure(path)
        except MeasureError as e:
            sys.stderr.write('%s: %s\n' % (path, e))
            status = 1
            continue
        m = dict(path=path, **m)
        sys.stdout.write(json.dumps(m) + '\n')
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
