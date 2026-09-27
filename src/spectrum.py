#!/usr/bin/env python3
"""Average power spectrum of an audio file, stdlib only.

Cascaded IIR highpass filters are not steep enough to measure a narrow band --
their skirt leaks lower-frequency energy into the result, which makes a 320kbps
transcode look identical to genuine lossless. An FFT does not have that
problem, so this computes the spectrum directly.

No numpy on stock macOS python, so the FFT is here: iterative radix-2, which
is fast enough at 4096 points to analyse a whole library in a couple of
minutes.
"""
import cmath
import math
import subprocess

WINDOW = 4096
WINDOWS = 28          # spread across the track, skipping intro and outro
SAMPLE_RATE = 44100


def fft(a):
    """Iterative radix-2 Cooley-Tukey. len(a) must be a power of two."""
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        ang = -2 * math.pi / length
        wl = cmath.exp(1j * ang)
        for i in range(0, n, length):
            w = 1 + 0j
            half = length >> 1
            for k in range(i, i + half):
                u = a[k]
                v = a[k + half] * w
                a[k] = u + v
                a[k + half] = u - v
                w *= wl
        length <<= 1
    return a


def decode(path, sr=SAMPLE_RATE):
    """Decode to mono 16-bit PCM at a known rate."""
    out = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", path, "-ac", "1", "-ar", str(sr),
         "-f", "s16le", "-"],
        capture_output=True, timeout=300)
    return out.stdout if out.returncode == 0 else b""


def average_spectrum(path, sr=SAMPLE_RATE):
    """Return (freqs, dB levels) averaged over windows across the track."""
    raw = decode(path, sr)
    total = len(raw) // 2
    if total < WINDOW * 4:
        return None, None

    # Skip the first and last 10%: fades and silence skew the average.
    start, end = int(total * 0.1), int(total * 0.9)
    span = end - start - WINDOW
    if span <= 0:
        return None, None
    step = max(1, span // WINDOWS)

    hann = [0.5 - 0.5 * math.cos(2 * math.pi * i / (WINDOW - 1)) for i in range(WINDOW)]
    acc = [0.0] * (WINDOW // 2)
    used = 0
    for w in range(WINDOWS):
        off = start + w * step
        if off + WINDOW > total:
            break
        chunk = raw[off * 2:(off + WINDOW) * 2]
        if len(chunk) < WINDOW * 2:
            break
        samples = []
        for i in range(WINDOW):
            lo = chunk[i * 2]
            hi = chunk[i * 2 + 1]
            v = lo | (hi << 8)
            if v >= 32768:
                v -= 65536
            samples.append(complex(v / 32768.0 * hann[i], 0.0))
        spec = fft(samples)
        for i in range(WINDOW // 2):
            acc[i] += abs(spec[i]) ** 2
        used += 1
    if not used:
        return None, None

    peak = max(acc) or 1e-30
    freqs = [i * sr / WINDOW for i in range(WINDOW // 2)]
    db = [10 * math.log10(max(v / used, 1e-30) / (peak / used)) for v in acc]
    return freqs, db


def spectral_edge(freqs, db, floor_db=-80.0):
    """Highest frequency still carrying energy above `floor_db` (peak-relative).

    This is the number that separates lossy from lossless: an encoder's lowpass
    puts a hard ceiling here, while genuine lossless runs to Nyquist.
    """
    for i in range(len(freqs) - 1, -1, -1):
        if db[i] > floor_db:
            return freqs[i]
    return 0.0


def cliff(freqs, db, edge_hz):
    """How abruptly the spectrum falls at the edge, in dB per kHz."""
    lo = edge_hz - 1000
    a = [db[i] for i, f in enumerate(freqs) if lo - 250 <= f <= lo + 250]
    b = [db[i] for i, f in enumerate(freqs) if edge_hz + 250 <= f <= edge_hz + 1250]
    if not a or not b:
        return 0.0
    return (sum(a) / len(a)) - (sum(b) / len(b))
