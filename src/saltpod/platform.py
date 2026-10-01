"""Capability-detecting platform adapter: macOS gets native tools, everything
else gets the portable path that already works.

WHY THIS EXISTS. `curate.py`, `apply.py` and `local_index.py` each shell out
to `ffmpeg`/`ffprobe` directly, which is the only thing that runs today but
drags 36 MB of homebrew dylibs along for jobs macOS already does itself
(research/MACOS-ADAPTERS.md). Measured there:

    afconvert -f m4af -d alac in.wav out.m4a   ->  alac, 44100, 2ch, 16-bit
    ffmpeg    -c:a alac                        ->  alac, 44100, 2ch, 16-bit
    audio md5: IDENTICAL

    sips -z 128 128 / -z 320 320   -> exactly 128 / 320 px, what ArtworkDB wants

`/usr/bin/afconvert` and `/usr/bin/sips` ship with every Mac; nothing to
bundle, nothing to sign. Every other OS -- and a Mac missing one of these,
which should never happen but is cheap to check for -- gets the ffmpeg path
that already works everywhere. The caller never branches on OS: it calls
`to_alac()` / `resize_image()` / `watch_mounts()` / `watch_tree()` and the
adapter picks, returning which backend actually ran so the caller can log it.

Nothing in this module is wired up yet; it is additive and self-contained.

THE RE-TESTED PART OF THE CLAIM ABOVE. A bare `ffmpeg -c:a alac` (the literal
command namedropped for "elsewhere") fails outright on a real file here that
carries embedded cover art: GTA SA radio's "01 - Jingle (1).mp3" has an mjpeg
video stream, and ffmpeg's ipod/mp4 muxer refuses to carry it, producing a
zero-byte output. `apply.py.convert_to_alac` already solved this with
`-vn -map 0:a:0`, so the ffmpeg path here uses that too -- it is not optional,
it is the difference between working and silently producing nothing on any
of the 1,562 tracks in the index that have art.

A SEPARATE FINDING, kept out of the shipped differential rather than used as
its test case: that same MP3, run through both backends with `-vn -map
0:a:0` in place, still disagreed -- afconvert decoded it internally at
32-bit, ffmpeg at 24-bit, and the ALAC md5s differed. This is a lossy-source
artifact (MP3 has no "real" bit depth to preserve; the two decoders made
different choices filling one in) and not a backend bug in the sense that
matters here, because `apply.py` never calls ALAC conversion on an MP3 in the
first place -- only on FLAC/WAV/AIFF/ALAC/OGG, which it copies or converts
losslessly. Re-run on a real WAV (Beatles "Her Majesty", 4.4 MB) both
backends gave alac/44100/2ch/16-bit with an identical md5, matching the
research doc exactly. `selftest()` below picks a WAV for this reason.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading

# A fallback, never an override -- mirrors apply.py's FF_ENV and curate.py's
# DEV_DIR. An unaccepted Xcode licence makes the Command Line Tools refuse to
# run; setting DEVELOPER_DIR to them directly sidesteps it without sudo. A
# machine with its own DEVELOPER_DIR, or an accepted licence, keeps its own.
_FF_ENV = {**os.environ,
           'DEVELOPER_DIR': os.environ.get('DEVELOPER_DIR')
                            or '/Library/Developer/CommandLineTools'}

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_INDEX = os.path.join(_ROOT, 'data', 'local', 'index.json')
_ART_DIR = os.path.join(_ROOT, 'data', 'local', 'art')

# Same set `local_index.py` indexes against, duplicated rather than imported:
# this module is meant to stay a generic OS adapter, not grow a dependency on
# the audio-library code that happens to be its first caller.
_AUDIO_EXT = {'.mp3', '.m4a', '.aiff', '.aif', '.flac', '.wav', '.alac', '.aac', '.ogg'}


# =============================================================== capabilities

_DETECT = None


def caps():
    """Detected capabilities, probed once per process and cached.

    Every flag comes from actually looking -- `os.uname()`, `shutil.which()`,
    `os.path.exists` -- never from guessing by platform name. `backends` is
    the live dispatch table: `to_alac()`/`resize_image()`/`watch_mounts()`/
    `watch_tree()` all read it fresh on every call, so it can move at
    runtime. Two things move it: `selftest()` forcing ffmpeg if the ALAC
    differential ever disagrees, and a native watcher that raises at the
    moment it is actually started, which downgrades itself to `poll` for the
    rest of the process rather than failing the same way on every call.
    """
    global _DETECT
    if _DETECT is not None:
        return _DETECT
    try:
        is_macos = os.uname().sysname == 'Darwin'
    except AttributeError:
        is_macos = False        # no os.uname() at all: not macOS, not Linux

    have_afconvert = is_macos and os.path.exists('/usr/bin/afconvert')
    have_sips = is_macos and os.path.exists('/usr/bin/sips')
    have_ffmpeg = bool(shutil.which('ffmpeg'))
    have_ffprobe = bool(shutil.which('ffprobe'))
    have_da = is_macos and _probe_diskarbitration()
    have_fsevents = is_macos and _probe_fsevents()

    _DETECT = {
        'darwin': is_macos,
        'afconvert': have_afconvert,
        'sips': have_sips,
        'ffmpeg': have_ffmpeg,
        'ffprobe': have_ffprobe,
        'diskarbitration': have_da,
        'fsevents': have_fsevents,
        'backends': {
            'to_alac': 'afconvert' if have_afconvert else 'ffmpeg',
            'resize_image': 'sips' if have_sips else 'ffmpeg',
            'watch_mounts': 'diskarbitration' if have_da else 'poll',
            'watch_tree': 'fsevents' if have_fsevents else 'poll',
        },
    }
    return _DETECT


# ===================================================================== alac

# ALAC carries the SOURCE BIT DEPTH in its format flags, and afconvert
# defaults to 32-bit when you do not say. This was nearly a shipped bug:
#
#   source              flac 44100 2ch 16-bit   18.6 MB
#   ffmpeg -c:a alac     alac 44100 2ch 16-bit   19.2 MB
#   afconvert -d alac    alac 44100 2ch 32-bit   46.3 MB     <-- 2.4x
#   afconvert -d alac/1  alac 44100 2ch 16-bit   19.1 MB
#
# All four decode to the SAME audio md5, which is exactly why a differential
# that compares only the audio would have passed it. The file on a 160 GB
# iPod would have been two and a half times the size it needed to be, and
# the Classic's decoder is specified for 16-bit ALAC -- so it may well not
# have played at all.
_ALAC_FLAG = {16: '1', 20: '2', 24: '3', 32: '4'}


def _source_bit_depth(src):
    """The source's bit depth, or None. ffprobe, because it is already here."""
    try:
        r = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', 'a:0',
                            '-show_entries', 'stream=bits_per_raw_sample,bits_per_sample',
                            '-of', 'default=nw=1:nk=1', src],
                           capture_output=True, text=True, timeout=30)
        for line in (r.stdout or '').split():
            n = int(line)
            if n in _ALAC_FLAG:
                return n
    except Exception:
        pass
    return None


def _to_alac_afconvert(src, dst, timeout=600):
    depth = _source_bit_depth(src)
    # 16 when the source will not say: every convertible file in this library
    # is 16-bit, and the device wants 16-bit. Guessing 32 is what afconvert
    # does on its own and it is the wrong guess.
    fmt = 'alac/' + _ALAC_FLAG.get(depth or 16, '1')
    r = subprocess.run(['/usr/bin/afconvert', '-f', 'm4af', '-d', fmt, src, dst],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError((r.stderr or r.stdout or 'afconvert failed').strip()[:500])


def _to_alac_ffmpeg(src, dst, timeout=600):
    # -vn -map 0:a:0: without this, a source carrying embedded cover art (an
    # mjpeg video stream -- 1,562 of 4,049 tracks in the index have one) makes
    # the mp4/ipod muxer refuse the video and write a zero-byte file. See the
    # module docstring: measured on a real file, not assumed.
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src,
                        '-vn', '-map', '0:a:0', '-c:a', 'alac', dst],
                       capture_output=True, text=True, timeout=timeout, env=_FF_ENV)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError((r.stderr or 'ffmpeg failed').strip()[:500])


def to_alac(src, dst):
    """Convert `src` to ALAC at `dst`. {'ok', 'backend', 'error'}.

    macOS picks afconvert; anywhere else, or if afconvert is missing, ffmpeg.
    Measured identical on a real WAV (module docstring) -- if `selftest()`
    ever finds that untrue on this machine, it flips `caps()['backends']` to
    ffmpeg and every call after that honours it.
    """
    c = caps()
    if c['backends']['to_alac'] == 'afconvert':
        try:
            _to_alac_afconvert(src, dst)
            return {'ok': True, 'backend': 'afconvert', 'error': None}
        except Exception as e:
            return {'ok': False, 'backend': 'afconvert', 'error': str(e)}
    if c['ffmpeg']:
        try:
            _to_alac_ffmpeg(src, dst)
            return {'ok': True, 'backend': 'ffmpeg', 'error': None}
        except Exception as e:
            return {'ok': False, 'backend': 'ffmpeg', 'error': str(e)}
    return {'ok': False, 'backend': 'ffmpeg', 'error': 'neither afconvert nor ffmpeg is available'}


# ============================================================== image resize
#
# TWO DIFFERENT OPERATIONS, and conflating them would have quietly squashed
# every non-square cover in the library. `sips -z H W` resamples to exactly
# those dimensions and does NOT preserve aspect ratio; ffmpeg's
# `scale=...:force_original_aspect_ratio=increase,crop=...` scales to COVER
# and then crops the overflow. On a square source they agree exactly, which
# is most album art and is why this would have looked fine in testing.
#
#   resize_image   exact dimensions, aspect ignored     (the primitive)
#   resize_cover   scale to cover, centre-crop          (what artwork wants)


def _pixel_size(path):
    """(width, height) via sips, or None. sips -g prints `key: value` lines."""
    try:
        r = subprocess.run(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', path],
                           capture_output=True, text=True, timeout=30)
        got = {}
        for line in (r.stdout or '').splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                got[k.strip()] = v.strip()
        return int(got['pixelWidth']), int(got['pixelHeight'])
    except Exception:
        return None


def _cover_sips(src, dst, w, h, timeout=60):
    """Scale to cover, then centre-crop -- two sips calls, because sips has no
    scale-to-cover of its own. The proportional target is computed here rather
    than left to sips, so the aspect ratio is preserved by arithmetic instead
    of by hoping a flag does it."""
    size = _pixel_size(src)
    if not size:
        raise RuntimeError('sips could not read the image size')
    sw, sh = size
    if sw <= 0 or sh <= 0:
        raise RuntimeError('image reports a zero dimension')
    scale = max(w / float(sw), h / float(sh))
    nw, nh = max(w, int(round(sw * scale))), max(h, int(round(sh * scale)))
    tmp = dst + '.cover.tmp'
    try:
        # -z takes HEIGHT then WIDTH, the opposite of every other tool here.
        r = subprocess.run(['/usr/bin/sips', '-z', str(nh), str(nw), src, '--out', tmp],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError((r.stderr or r.stdout or 'sips scale failed').strip()[:400])
        # -c crops to HEIGHT WIDTH, centred, which is what we want.
        r = subprocess.run(['/usr/bin/sips', '-c', str(h), str(w), tmp, '--out', dst],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError((r.stderr or r.stdout or 'sips crop failed').strip()[:400])
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _cover_ffmpeg(src, dst, w, h, timeout=60):
    """The invocation curate.py has used for the 320x320 ArtworkDB thumbnail."""
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf',
                        'scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d'
                        % (w, h, w, h), '-q:v', '3', dst],
                       capture_output=True, text=True, timeout=timeout, env=_FF_ENV)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError((r.stderr or 'ffmpeg failed').strip()[:400])


def resize_cover(src, dst, w, h):
    """Scale to cover and centre-crop to exactly w x h. {'ok','backend','error'}.

    This is the one the iPod's artwork needs: the Classic's thumbnails are
    square (128x128 and 320x320) and a squashed cover is worse than a
    cropped one.
    """
    c = caps()
    order = ['sips', 'ffmpeg'] if c['backends']['resize_image'] == 'sips' else ['ffmpeg']
    err = None
    for backend in order:
        if backend == 'sips' and not c['sips']:
            continue
        if backend == 'ffmpeg' and not c['ffmpeg']:
            continue
        try:
            (_cover_sips if backend == 'sips' else _cover_ffmpeg)(src, dst, w, h)
            return {'ok': True, 'backend': backend, 'error': None}
        except Exception as e:
            err = '%s: %s' % (backend, e)
    return {'ok': False, 'backend': order[-1] if order else 'none',
            'error': err or 'no image backend available'}



def _resize_sips(src, dst, w, h, timeout=60):
    # sips takes HEIGHT then WIDTH, which is the opposite of every other tool
    # here (and of this function's own argument order). Measured: `-z 128 128`
    # and `-z 320 320` are square so it never showed up until a non-square
    # size would expose it -- get this backwards and every landscape thumbnail
    # comes out rotated 90 degrees from what was asked for.
    r = subprocess.run(['/usr/bin/sips', '-z', str(h), str(w), src, '--out', dst],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError((r.stderr or r.stdout or 'sips failed').strip()[:500])


def _resize_ffmpeg(src, dst, w, h, timeout=60):
    # Same invocation curate.py's artwork handler already uses for the 320x320
    # ArtworkDB thumbnail: scale up to cover, then crop to exact. force_...=
    # increase (not decrease) matters -- a plain scale leaves the wrong size
    # on anything that is not already square.
    vf = 'scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d' % (w, h, w, h)
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', vf, '-q:v', '3', dst],
                       capture_output=True, text=True, timeout=timeout, env=_FF_ENV)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError((r.stderr or 'ffmpeg failed').strip()[:500])


def resize_image(src, dst, w, h):
    """Resize+crop `src` to exactly `w`x`h` at `dst`. {'ok', 'backend', 'error'}."""
    c = caps()
    if c['backends']['resize_image'] == 'sips':
        try:
            _resize_sips(src, dst, w, h)
            return {'ok': True, 'backend': 'sips', 'error': None}
        except Exception as e:
            return {'ok': False, 'backend': 'sips', 'error': str(e)}
    if c['ffmpeg']:
        try:
            _resize_ffmpeg(src, dst, w, h)
            return {'ok': True, 'backend': 'ffmpeg', 'error': None}
        except Exception as e:
            return {'ok': False, 'backend': 'ffmpeg', 'error': str(e)}
    return {'ok': False, 'backend': 'ffmpeg', 'error': 'neither sips nor ffmpeg is available'}


# ====================================================================== watch

class Watcher:
    """What `watch_mounts()`/`watch_tree()` return: one job, stopping cleanly.

    `.backend` says what actually ran, not what `caps()` predicted -- a
    native path that failed at the moment it was started reports itself as
    `poll (... failed: ...)` rather than silently becoming indistinguishable
    from the ordinary poll fallback.
    """

    def __init__(self, backend, stop_fn):
        self.backend = backend
        self._stop_fn = stop_fn
        self._stopped = False

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        try:
            self._stop_fn()
        except Exception:
            pass

    def __repr__(self):
        return 'Watcher(backend=%r, stopped=%s)' % (self.backend, self._stopped)


# --------------------------------------------------------- ctypes: shared CF

# Both native watchers need a CFRunLoop to live on; a daemon thread runs it
# and is torn down by stopping the loop from outside, not by killing the
# thread. Bound lazily and cached -- loading a framework costs real time and
# every caller after the first one just wants the same handles back.
_CF_DA = None   # (CoreFoundation, DiskArbitration, kCFRunLoopDefaultMode, DACallbackType)
_CF_CS = None   # (CoreFoundation, CoreServices, kCFRunLoopDefaultMode, kCFTypeArrayCallBacks, FSEventStreamCallbackType)

_K_UTF8 = 0x08000100                        # kCFStringEncodingUTF8
_K_SINCE_NOW = 0xFFFFFFFFFFFFFFFF           # kFSEventStreamEventIdSinceNow
_FLAG_FILE_EVENTS = 0x00000010              # kFSEventStreamCreateFlagFileEvents
_FLAG_ITEM_CREATED = 0x00000100
_FLAG_ITEM_REMOVED = 0x00000200
_FLAG_ITEM_IS_DIR = 0x00020000


def _bind_diskarbitration():
    global _CF_DA
    if _CF_DA is not None:
        return _CF_DA
    CF = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    DA = ctypes.CDLL('/System/Library/Frameworks/DiskArbitration.framework/DiskArbitration')

    CF.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    CF.CFRunLoopRun.restype = None
    CF.CFRunLoopStop.argtypes = [ctypes.c_void_p]
    CF.CFRunLoopStop.restype = None
    CF.CFRelease.argtypes = [ctypes.c_void_p]
    CF.CFRelease.restype = None

    DACallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
    DA.DASessionCreate.restype = ctypes.c_void_p
    DA.DASessionCreate.argtypes = [ctypes.c_void_p]
    DA.DASessionScheduleWithRunLoop.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    DA.DASessionScheduleWithRunLoop.restype = None
    DA.DARegisterDiskAppearedCallback.argtypes = [ctypes.c_void_p, ctypes.c_void_p, DACallback, ctypes.c_void_p]
    DA.DARegisterDiskAppearedCallback.restype = None
    DA.DARegisterDiskDisappearedCallback.argtypes = [ctypes.c_void_p, ctypes.c_void_p, DACallback, ctypes.c_void_p]
    DA.DARegisterDiskDisappearedCallback.restype = None
    # DISK APPEARED IS NOT DISK MOUNTED, and that one word was the whole bug.
    # The appeared callback fires when the device node shows up, which is
    # BEFORE the volume is mounted -- so a rescan of /Volumes from inside it
    # sees nothing new, and the baseline it failed to update then swallows the
    # matching unmount as well. Measured with `hdiutil attach` on a real disk
    # image: zero events across an attach and a detach, while the callbacks
    # themselves were firing perfectly.
    #
    # The mount itself arrives as a DESCRIPTION CHANGE -- the volume path key
    # gets a value. Registering for all description changes and re-scanning is
    # the smallest correct fix and needs no CFDictionary parsing.
    DADescChanged = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    DA.DARegisterDiskDescriptionChangedCallback.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, DADescChanged, ctypes.c_void_p]
    DA.DARegisterDiskDescriptionChangedCallback.restype = None

    kmode = ctypes.c_void_p.in_dll(CF, 'kCFRunLoopDefaultMode')
    _CF_DA = (CF, DA, kmode, DACallback, DADescChanged)
    return _CF_DA


def _bind_fsevents():
    global _CF_CS
    if _CF_CS is not None:
        return _CF_CS
    CF = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    CS = ctypes.CDLL('/System/Library/Frameworks/CoreServices.framework/CoreServices')

    CF.CFStringCreateWithCString.restype = ctypes.c_void_p
    CF.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    CF.CFArrayCreate.restype = ctypes.c_void_p
    CF.CFArrayCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_long, ctypes.c_void_p]
    CF.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    CF.CFRunLoopRun.restype = None
    CF.CFRunLoopStop.argtypes = [ctypes.c_void_p]
    CF.CFRunLoopStop.restype = None
    CF.CFRelease.argtypes = [ctypes.c_void_p]
    CF.CFRelease.restype = None

    FSEventStreamCallback = ctypes.CFUNCTYPE(
        None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64))
    CS.FSEventStreamCreate.restype = ctypes.c_void_p
    CS.FSEventStreamCreate.argtypes = [
        ctypes.c_void_p, FSEventStreamCallback, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_uint64, ctypes.c_double, ctypes.c_uint32]
    CS.FSEventStreamScheduleWithRunLoop.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    CS.FSEventStreamScheduleWithRunLoop.restype = None
    CS.FSEventStreamStart.argtypes = [ctypes.c_void_p]
    CS.FSEventStreamStart.restype = ctypes.c_bool
    CS.FSEventStreamStop.argtypes = [ctypes.c_void_p]
    CS.FSEventStreamStop.restype = None
    CS.FSEventStreamInvalidate.argtypes = [ctypes.c_void_p]
    CS.FSEventStreamInvalidate.restype = None
    CS.FSEventStreamRelease.argtypes = [ctypes.c_void_p]
    CS.FSEventStreamRelease.restype = None

    kmode = ctypes.c_void_p.in_dll(CF, 'kCFRunLoopDefaultMode')
    karr = ctypes.c_void_p.in_dll(CF, 'kCFTypeArrayCallBacks')
    _CF_CS = (CF, CS, kmode, karr, FSEventStreamCallback)
    return _CF_CS


def _probe_diskarbitration():
    """Can a DiskArbitration session actually start and stop, right now.

    Genuinely constructs and tears one down rather than just checking the
    framework file exists -- a session that creates, schedules, and stops
    cleanly is the honest bar for trusting the native path by default.
    Bounded to ~2s either way so a stuck run loop cannot hang `caps()`; the
    thread is a daemon, so a failure to join just leaves it to die with the
    process instead of blocking anything.
    """
    try:
        CF, DA, kmode, DACallback, _DescChanged = _bind_diskarbitration()
        session = DA.DASessionCreate(None)
        if not session:
            return False
        box = {}
        ready = threading.Event()

        def _runner():
            rl = CF.CFRunLoopGetCurrent()
            box['rl'] = rl
            DA.DASessionScheduleWithRunLoop(session, rl, kmode)
            ready.set()
            CF.CFRunLoopRun()

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        started = ready.wait(timeout=2.0)
        rl = box.get('rl')
        if rl:
            CF.CFRunLoopStop(rl)
        t.join(timeout=2.0)
        try:
            CF.CFRelease(session)
        except Exception:
            pass
        return bool(started)
    except Exception:
        return False


def _probe_fsevents():
    """Can an FSEvents stream actually start and stop, right now, on a
    throwaway directory. Same bar and same bound as the DiskArbitration probe."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix='saltpod-platform-probe-')
    stream = cfarray = path_cf = None
    try:
        CF, CS, kmode, karr, FSEventStreamCallback = _bind_fsevents()
        cb = FSEventStreamCallback(lambda *a: None)
        path_cf = CF.CFStringCreateWithCString(None, tmp.encode('utf-8'), _K_UTF8)
        if not path_cf:
            return False
        arr = (ctypes.c_void_p * 1)(path_cf)
        cfarray = CF.CFArrayCreate(None, arr, 1, ctypes.byref(karr))
        if not cfarray:
            return False
        stream = CS.FSEventStreamCreate(None, cb, None, cfarray, _K_SINCE_NOW, 0.1, _FLAG_FILE_EVENTS)
        if not stream:
            return False

        box = {}
        ready = threading.Event()

        def _runner():
            rl = CF.CFRunLoopGetCurrent()
            box['rl'] = rl
            CS.FSEventStreamScheduleWithRunLoop(stream, rl, kmode)
            box['started'] = CS.FSEventStreamStart(stream)
            ready.set()
            CF.CFRunLoopRun()

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        ready.wait(timeout=2.0)
        started = bool(box.get('started'))
        rl = box.get('rl')
        if started:
            CS.FSEventStreamStop(stream)
            CS.FSEventStreamInvalidate(stream)
        if rl:
            CF.CFRunLoopStop(rl)
        t.join(timeout=2.0)
        return started
    except Exception:
        return False
    finally:
        try:
            if stream:
                CS.FSEventStreamRelease(stream)
            if cfarray:
                CF.CFRelease(cfarray)
            if path_cf:
                CF.CFRelease(path_cf)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------- watch_mounts

def _list_volumes():
    """Mounted volume names under /Volumes -- the set both backends diff
    against. `os.path.ismount` filters out a stale directory entry left
    behind by an unclean unmount; `/Volumes` not existing (not macOS) is not
    an error here, just an empty answer."""
    try:
        names = os.listdir('/Volumes')
    except OSError:
        return set()
    return {n for n in names if os.path.ismount(os.path.join('/Volumes', n))}


def _watch_mounts_poll(on_change, interval=2.0, note=None):
    """The required-correct fallback: poll os.path.ismount/os.listdir every
    2s, diff the set, call on_change on a change. This is the default for
    every non-macOS machine and stays the default on macOS too unless the
    native path is verified (see caps())."""
    stop_event = threading.Event()

    def _loop():
        prev = _list_volumes()
        while not stop_event.wait(interval):
            cur = _list_volumes()
            if cur != prev:
                added, removed = sorted(cur - prev), sorted(prev - cur)
                prev = cur
                try:
                    on_change({'added': added, 'removed': removed, 'volumes': sorted(cur)})
                except Exception:
                    pass          # a bug in the caller's handler must not kill the thread

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

    def _stop():
        stop_event.set()
        t.join(timeout=interval + 2)

    backend = 'poll' if not note else 'poll (diskarbitration %s)' % note
    return Watcher(backend, _stop)


def _watch_mounts_diskarbitration(on_change):
    """DiskArbitration as a trigger, not a parser. The callback does not try
    to decode DADiskRef -> CFDictionary -> CFURL for the mount path (real,
    but a much larger surface of ctypes to get right for no real benefit
    here) -- it just re-lists /Volumes, the same way the poll fallback does,
    so both backends produce the exact same event shape and the only
    difference is latency: instant instead of up to 2s."""
    CF, DA, kmode, DACallback, DADescChanged = _bind_diskarbitration()
    session = DA.DASessionCreate(None)
    if not session:
        raise RuntimeError('DASessionCreate returned NULL')

    lock = threading.Lock()
    # Baseline taken before the session is scheduled: DiskArbitration fires
    # the appeared-callback once for every already-mounted disk as soon as
    # you register (measured: 63 calls on this machine's one external drive
    # plus its internal containers/snapshots), and none of that is a change.
    state = {'volumes': _list_volumes()}

    def _rescan():
        cur = _list_volumes()
        with lock:
            prev = state['volumes']
            if cur == prev:
                return
            added, removed = sorted(cur - prev), sorted(prev - cur)
            state['volumes'] = cur
        try:
            on_change({'added': added, 'removed': removed, 'volumes': sorted(cur)})
        except Exception:
            pass

    def _appeared(disk, ctx):
        _rescan()

    def _disappeared(disk, ctx):
        _rescan()

    def _changed(disk, keys, ctx):
        _rescan()

    appeared_cb = DACallback(_appeared)
    disappeared_cb = DACallback(_disappeared)
    changed_cb = DADescChanged(_changed)

    # The ctypes trampolines must outlive this function or the run loop calls
    # into freed memory. Held here rather than in a local that falls out of
    # scope the moment the watcher is returned.
    box = {'keepalive': (appeared_cb, disappeared_cb, changed_cb)}
    ready = threading.Event()

    def _runner():
        rl = CF.CFRunLoopGetCurrent()
        box['rl'] = rl
        DA.DASessionScheduleWithRunLoop(session, rl, kmode)
        DA.DARegisterDiskAppearedCallback(session, None, appeared_cb, None)
        DA.DARegisterDiskDisappearedCallback(session, None, disappeared_cb, None)
        # NULL watch keys: every description change. The one that matters is
        # the volume path arriving, which is the actual moment of mounting.
        DA.DARegisterDiskDescriptionChangedCallback(session, None, None, changed_cb, None)
        ready.set()
        CF.CFRunLoopRun()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    if not ready.wait(timeout=2.0):
        raise RuntimeError('DiskArbitration run loop did not start in time')

    def _stop():
        rl = box.get('rl')
        if rl:
            CF.CFRunLoopStop(rl)
        thread.join(timeout=2.0)
        try:
            CF.CFRelease(session)
        except Exception:
            pass

    w = Watcher('diskarbitration', _stop)
    w._keepalive = (appeared_cb, disappeared_cb)   # must outlive anything that can call them
    return w


def watch_mounts(on_change):
    """Watch for drives mounting/unmounting. Returns a Watcher (`.stop()`).

    `on_change({'added': [...], 'removed': [...], 'volumes': [...]})` -- names
    under /Volumes, both backends, same shape. macOS tries DiskArbitration
    (instant); everywhere else, and if DiskArbitration fails at the moment it
    is actually started, a 2s poll that is verified correct and is the
    default everywhere this has not been proven to work.
    """
    c = caps()
    if c['backends']['watch_mounts'] == 'diskarbitration':
        try:
            return _watch_mounts_diskarbitration(on_change)
        except Exception as e:
            # Genuinely unexpected: the one-time probe in caps() passed. Do
            # not keep trying this every call -- downgrade for the rest of
            # the process, same as the ALAC differential does on mismatch.
            c['diskarbitration'] = False
            c['backends']['watch_mounts'] = 'poll'
            return _watch_mounts_poll(on_change, note='failed: %s' % e)
    return _watch_mounts_poll(on_change)


# ---------------------------------------------------------------- watch_tree

def _tree_snapshot(root):
    """{path: mtime} for every audio file under root. Walks, never opens a
    file -- this is the same promise local_index.py's probe() does not make
    and ffprobe's 32ms/file is exactly the cost this sidesteps for a watcher
    that has to run continuously rather than once."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.startswith('._'):
                continue          # AppleDouble stub, see local_index.py
            if os.path.splitext(fn)[1].lower() not in _AUDIO_EXT:
                continue
            p = os.path.join(dirpath, fn)
            try:
                out[p] = os.path.getmtime(p)
            except OSError:
                pass              # vanished between listdir and stat
    return out


def _watch_tree_poll(root, on_change, interval=2.0, note=None):
    """The required-correct fallback: walk the tree every 2s, diff mtimes."""
    stop_event = threading.Event()

    def _loop():
        prev = _tree_snapshot(root)
        while not stop_event.wait(interval):
            cur = _tree_snapshot(root)
            added = sorted(set(cur) - set(prev))
            removed = sorted(set(prev) - set(cur))
            modified = sorted(p for p in (set(cur) & set(prev)) if cur[p] != prev[p])
            prev = cur
            if added or removed or modified:
                try:
                    on_change({'added': added, 'removed': removed, 'modified': modified})
                except Exception:
                    pass

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

    def _stop():
        stop_event.set()
        t.join(timeout=interval + 2)

    backend = 'poll' if not note else 'poll (fsevents %s)' % note
    return Watcher(backend, _stop)


def _watch_tree_fsevents(root, on_change, latency=0.3):
    """FSEvents with kFSEventStreamCreateFlagFileEvents, which gives individual
    file paths rather than just the containing directory (verified: without
    this flag a file write inside a watched tmpdir is reported as the
    directory having changed, which is not enough to know what to re-probe)."""
    if not os.path.isdir(root):
        raise RuntimeError('not a directory: %s' % root)
    CF, CS, kmode, karr, FSEventStreamCallback = _bind_fsevents()

    def _cb(streamref, info, numevents, eventpaths, eventflags, eventids):
        paths = ctypes.cast(eventpaths, ctypes.POINTER(ctypes.c_char_p))
        added, removed, modified = [], [], []
        for i in range(numevents):
            raw = paths[i]
            if not raw:
                continue
            p = raw.decode('utf-8', 'replace')
            flags = eventflags[i]
            if flags & _FLAG_ITEM_IS_DIR:
                continue
            if os.path.basename(p).startswith('._'):
                continue
            if os.path.splitext(p)[1].lower() not in _AUDIO_EXT:
                continue
            if flags & _FLAG_ITEM_REMOVED:
                removed.append(p)
            elif flags & _FLAG_ITEM_CREATED:
                added.append(p)
            else:
                modified.append(p)
        if added or removed or modified:
            try:
                on_change({'added': added, 'removed': removed, 'modified': modified})
            except Exception:
                pass

    cb = FSEventStreamCallback(_cb)
    path_cf = CF.CFStringCreateWithCString(None, root.encode('utf-8'), _K_UTF8)
    if not path_cf:
        raise RuntimeError('CFStringCreateWithCString failed')
    arr = (ctypes.c_void_p * 1)(path_cf)
    cfarray = CF.CFArrayCreate(None, arr, 1, ctypes.byref(karr))
    if not cfarray:
        CF.CFRelease(path_cf)
        raise RuntimeError('CFArrayCreate failed')

    stream = CS.FSEventStreamCreate(None, cb, None, cfarray, _K_SINCE_NOW, latency, _FLAG_FILE_EVENTS)
    if not stream:
        CF.CFRelease(cfarray)
        CF.CFRelease(path_cf)
        raise RuntimeError('FSEventStreamCreate failed')

    box = {}
    ready = threading.Event()

    def _runner():
        rl = CF.CFRunLoopGetCurrent()
        box['rl'] = rl
        CS.FSEventStreamScheduleWithRunLoop(stream, rl, kmode)
        box['started'] = CS.FSEventStreamStart(stream)
        ready.set()
        CF.CFRunLoopRun()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    if not ready.wait(timeout=2.0) or not box.get('started'):
        rl = box.get('rl')
        if rl:
            CF.CFRunLoopStop(rl)
        thread.join(timeout=1.0)
        try:
            CS.FSEventStreamRelease(stream)
            CF.CFRelease(cfarray)
            CF.CFRelease(path_cf)
        except Exception:
            pass
        raise RuntimeError('FSEventStreamStart failed')

    def _stop():
        rl = box.get('rl')
        try:
            CS.FSEventStreamStop(stream)
            CS.FSEventStreamInvalidate(stream)
        except Exception:
            pass
        if rl:
            CF.CFRunLoopStop(rl)
        thread.join(timeout=2.0)
        try:
            CS.FSEventStreamRelease(stream)
            CF.CFRelease(cfarray)
            CF.CFRelease(path_cf)
        except Exception:
            pass

    w = Watcher('fsevents', _stop)
    w._keepalive = (cb,)
    return w


def watch_tree(root, on_change):
    """Watch `root` for audio files appearing/changing/disappearing.

    `on_change({'added': [...], 'removed': [...], 'modified': [...]})` -- full
    paths, both backends, same shape. macOS tries FSEvents; everywhere else,
    and if FSEvents fails at the moment it is actually started, a 2s polling
    walk comparing mtimes.
    """
    c = caps()
    if c['backends']['watch_tree'] == 'fsevents':
        try:
            return _watch_tree_fsevents(root, on_change)
        except Exception as e:
            c['fsevents'] = False
            c['backends']['watch_tree'] = 'poll'
            return _watch_tree_poll(root, on_change, note='failed: %s' % e)
    return _watch_tree_poll(root, on_change)


# =================================================================== selftest

def _find_sample_audio(max_bytes=10 * 1024 * 1024):
    """A small real file off the drive index, for the ALAC differential.

    WAV preferred over MP3, and not arbitrarily: `apply.py`'s CONVERT set is
    {flac, wav, aiff, aif, alac, ogg} -- ALAC conversion never runs on an MP3
    in production, MP3 is copied as-is. A WAV is also what the research doc
    itself measured. See the module docstring for what picking an MP3 here
    actually showed (a real, separate finding, deliberately not this test).
    """
    try:
        with open(_INDEX) as fh:
            d = json.load(fh)
    except Exception:
        return None
    tracks = d.get('tracks', [])
    for ext in ('.wav', '.mp3'):
        cands = sorted(
            (t for t in tracks if t.get('ext') == ext and t.get('size') and t['size'] < max_bytes),
            key=lambda t: t['size'])
        for t in cands:
            p = t.get('path')
            if p and os.path.exists(p):
                return p
    return None


def _find_sample_image():
    """A small real cached cover off disk, for the resize_image check."""
    try:
        names = [n for n in os.listdir(_ART_DIR) if n.lower().endswith(('.jpg', '.jpeg', '.png'))]
    except OSError:
        return None
    names.sort(key=lambda n: os.path.getsize(os.path.join(_ART_DIR, n)))
    for n in names:
        p = os.path.join(_ART_DIR, n)
        if os.path.exists(p):
            return p
    return None


def _ffprobe_audio_stream(path, timeout=60):
    r = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path],
                       capture_output=True, text=True, timeout=timeout, env=_FF_ENV)
    j = json.loads(r.stdout or '{}')
    return next((s for s in j.get('streams') or [] if s.get('codec_type') == 'audio'), {})


def _ffmpeg_audio_md5(path, timeout=120):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'md5', '-'],
                       capture_output=True, text=True, timeout=timeout, env=_FF_ENV)
    out = (r.stdout or '').strip()
    return out.split('=')[-1].strip() if '=' in out else out


def _image_dims(path):
    """Pixel (width, height), via sips if present, else ffprobe."""
    if caps()['sips']:
        r = subprocess.run(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', path],
                           capture_output=True, text=True, timeout=30)
        w = h = None
        for line in (r.stdout or '').splitlines():
            line = line.strip()
            if line.startswith('pixelWidth:'):
                w = int(line.split(':', 1)[1].strip())
            elif line.startswith('pixelHeight:'):
                h = int(line.split(':', 1)[1].strip())
        return w, h
    r = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path],
                       capture_output=True, text=True, timeout=30, env=_FF_ENV)
    j = json.loads(r.stdout or '{}')
    st = next((s for s in j.get('streams') or [] if s.get('codec_type') == 'video'), {})
    return st.get('width'), st.get('height')


def _selftest_alac():
    import shutil as _shutil
    import tempfile
    print()
    print('--- to_alac differential: afconvert vs ffmpeg ---')
    c = caps()
    if not (c['afconvert'] and c['ffmpeg']):
        print('  SKIPPED: need both present to compare (afconvert=%s ffmpeg=%s)'
              % (c['afconvert'], c['ffmpeg']))
        return True
    src = _find_sample_audio()
    if src is None:
        print('  SKIPPED: no .wav/.mp3 under 10 MB found via %s' % _INDEX)
        return True
    print('  source: %s' % src)
    tmpdir = tempfile.mkdtemp(prefix='saltpod-platform-')
    try:
        out_af = os.path.join(tmpdir, 'af.m4a')
        out_ff = os.path.join(tmpdir, 'ff.m4a')
        try:
            _to_alac_afconvert(src, out_af)
        except Exception as e:
            print('  afconvert FAILED: %s' % e)
            return False
        try:
            _to_alac_ffmpeg(src, out_ff)
        except Exception as e:
            print('  ffmpeg FAILED: %s' % e)
            return False

        st_af, st_ff = _ffprobe_audio_stream(out_af), _ffprobe_audio_stream(out_ff)

        def fmt(st, n):
            return ('%s -> codec=%s rate=%s ch=%s bits=%s (%d bytes)'
                    % (n, st.get('codec_name'), st.get('sample_rate'), st.get('channels'),
                       st.get('bits_per_raw_sample') or st.get('bits_per_sample'),
                       os.path.getsize(out_af if n == 'afconvert' else out_ff)))
        print('  ' + fmt(st_af, 'afconvert'))
        print('  ' + fmt(st_ff, 'ffmpeg'))

        md5_af, md5_ff = _ffmpeg_audio_md5(out_af), _ffmpeg_audio_md5(out_ff)
        print('  audio md5  afconvert=%s  ffmpeg=%s' % (md5_af, md5_ff))

        same_format = (st_af.get('codec_name') == st_ff.get('codec_name')
                       and st_af.get('sample_rate') == st_ff.get('sample_rate')
                       and st_af.get('channels') == st_ff.get('channels'))
        same_audio = bool(md5_af) and md5_af == md5_ff

        if same_audio and same_format:
            print('  MATCH: identical audio. afconvert stays the default.')
            return True

        print('  *** DISAGREEMENT: afconvert and ffmpeg produced different audio ***')
        print('  *** forcing ffmpeg as the to_alac default for the rest of this process ***')
        caps()['backends']['to_alac'] = 'ffmpeg'
        return False
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def _selftest_resize():
    import shutil as _shutil
    import tempfile
    print()
    print('--- resize_image (%s) ---' % caps()['backends']['resize_image'])
    img = _find_sample_image()
    if img is None:
        print('  SKIPPED: no cached art under %s' % _ART_DIR)
        return True
    tmpdir = tempfile.mkdtemp(prefix='saltpod-platform-')
    try:
        ok = True
        for w, h in ((128, 128), (320, 320)):
            dst = os.path.join(tmpdir, 'out_%dx%d.jpg' % (w, h))
            r = resize_image(img, dst, w, h)
            if not r['ok']:
                print('  %dx%d via %s: FAILED (%s)' % (w, h, r['backend'], r['error']))
                ok = False
                continue
            pw, ph = _image_dims(dst)
            got_ok = (pw == w and ph == h)
            print('  %dx%d via %-6s -> %sx%s  %s'
                  % (w, h, r['backend'], pw, ph, 'ok' if got_ok else 'MISMATCH'))
            ok = ok and got_ok
        return ok
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def _selftest_watch_tree():
    import shutil as _shutil
    import tempfile
    import time
    print()
    print('--- watch_tree (%s) ---' % caps()['backends']['watch_tree'])
    tmpdir = tempfile.mkdtemp(prefix='saltpod-platform-watch-')
    events = []
    seen = threading.Event()

    def _on(change):
        events.append(change)
        seen.set()

    try:
        w = watch_tree(tmpdir, _on)
    except Exception as e:
        print('  FAILED to start: %s' % e)
        _shutil.rmtree(tmpdir, ignore_errors=True)
        return False
    try:
        time.sleep(0.5)                           # let the watcher settle before writing
        testfile = os.path.join(tmpdir, 'probe.mp3')
        with open(testfile, 'wb') as fh:
            fh.write(b'\x00' * 16)
        got = seen.wait(timeout=5.0)
        w.stop()
        # FSEvents reports the fully resolved path -- /private/var/folders/...
        # even when tmpdir came back as /var/folders/... (macOS symlinks /var
        # to /private/var). Compare resolved paths, not raw strings, or every
        # fsevents run fails this check while actually working correctly.
        real_testfile = os.path.realpath(testfile)
        seen_added = {os.path.realpath(p) for e in events for p in e.get('added', [])}
        if got and real_testfile in seen_added:
            print('  %s saw the new file: ok' % w.backend)
            return True
        if got:
            print('  %s fired but did not list the new file as added: %r' % (w.backend, events))
            return False
        print('  %s: NOT VERIFIED -- no event observed within 5s' % w.backend)
        return False
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def _selftest_watch_mounts():
    import time
    print()
    print('--- watch_mounts (%s) ---' % caps()['backends']['watch_mounts'])
    got = []
    try:
        w = watch_mounts(lambda e: got.append(e))
    except Exception as e:
        print('  FAILED to start: %s' % e)
        return False
    time.sleep(1.0)
    w.stop()
    print('  started and stopped cleanly via %s' % w.backend)
    print('  NOT VERIFIED: no drive was plugged/unplugged during this run, so a real')
    print('  mount-change event was never exercised -- only that setup and teardown')
    print('  do not raise or hang.')
    if got:
        print('  (also saw %d mount-set change(s) during the 1s window: %r)' % (len(got), got))
    return True


def selftest():
    """Everything this module needs verified, against real files, under
    tempfile.mkdtemp() only. Never touches the library a sample is read from."""
    c = caps()
    print('capabilities:')
    for k in ('darwin', 'afconvert', 'sips', 'ffmpeg', 'ffprobe', 'diskarbitration', 'fsevents'):
        print('  %-16s %s' % (k, c[k]))
    print('  backends:')
    for k, v in c['backends'].items():
        print('    %-14s %s' % (k, v))

    ok = True
    ok = _selftest_alac() and ok
    ok = _selftest_resize() and ok
    ok = _selftest_watch_tree() and ok
    ok = _selftest_watch_mounts() and ok

    print()
    print('selftest %s' % ('PASSED' if ok else 'FAILED'))
    return ok


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if not a or a[0] != 'selftest':
        print('usage: python3 -m saltpod.platform selftest')
        return 2
    return 0 if selftest() else 1


if __name__ == '__main__':
    sys.exit(main())
