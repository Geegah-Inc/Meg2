#!/usr/bin/env python3
r"""
meg2_video_gui.py  -  MEG2 post-processing: turn a stored run (the timestamp folder) into a video / GIF.

  python meg2_video_gui.py            (no arguments needed)

Folder layout (one run = one timestamp folder, e.g.  "2026-10-02 01-53-13_N1_VII"):
    air-echo-I.dat  air-echo-Q.dat  air-noecho-I.dat  air-noecho-Q.dat     one frame of air = the baseline
    echo/      echo_I_1_o.dat   echo_Q_1_o.dat   echo_I_2_o.dat ...        sample frames, echo
    no-echo/   noecho_I_1_o.dat noecho_Q_1_o.dat ...                        sample frames, no-echo (taken continuously)
Frame n of the echo pairs with frame n of the no-echo.  Frame rate = from the time stamps (modification time) of the files.

1. Load the run folder.  The .dat format (float32 / float64 / int16 / text, header ...) is detected automatically; if the
   picture looks wrong use "Inspect file..." (it prints what is in the file) or set the format by hand.
2. Pick the variable, frame range, averaging, colours.
3. Preview one frame (the picture on the right is exactly what goes into the video), then Generate.

Averaging is applied to the raw I and Q frames (rolling mean over the last N frames), then the variable is derived.
The raw files are never modified.
"""
import os
import re
import sys
import json
import time
import queue
import shutil
import tempfile
import threading
import subprocess
import importlib
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception:                                    # the engine below also works without a display / tkinter
    tk = ttk = filedialog = messagebox = None

# =====================================================================================================================
START_FOLDER = ""            # optional: a run folder to load automatically when the window opens
PIXEL_PITCH_UM = 50.0        # MEG2 pixel pitch (editable in the window)
Z_SI_MRAYL = 19.6            # acoustic impedance of silicon (rho 2329 kg/m3 x c 8433 m/s) in MRayl
PREFS_FILE = os.path.join(os.path.expanduser("~"), ".meg2_video_gui.json")
FONT_FILES = ["arial.ttf", "Arial.ttf", "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
              "LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "DejaVuSans.ttf"]
# =====================================================================================================================

# --- variables that can be plotted ------------------------------------------------------------------------------------
# key, menu text, text under the title, data needed, description
#   needs:  ne = no-echo frames (recorded in the run or the baseline's mean no-echo),  bgiq = baseline echo mean,
#           bgne = baseline no-echo mean
RB = ("ne", "bgiq", "bgne")
VARS = [
    ("reflection", "Reflection coefficient  R", "Reflection coefficient", RB,
     "R = |echo - no-echo| of the sample / the same for the baseline (air).  1 = like air (total reflection), 0 = nothing reflected."),
    ("refl_db", "Reflection (dB)  20 log10 R", "Reflection (dB)", RB, "20 log10(R).  0 dB = like air."),
    ("power", "Reflected power  R²", "Reflected power  R²", RB, "Intensity reflectance R squared."),
    ("transmit", "Transmitted power  1 - R²", "Transmitted power  1 - R²", RB,
     "Share of the acoustic power that leaves the silicon into the sample (1 - R squared)."),
    ("impedance", "Acoustic impedance Z (MRayl), from |R|", "Acoustic impedance Z (MRayl)", RB,
     "Z = Z_Si (1 - R)/(1 + R).  Baseline = air (r = -1) and sample softer than silicon (Z < Z_Si).  Robust: uses the magnitude only."),
    ("impedance_iq", "Acoustic impedance Z (MRayl), signed from I/Q", "Acoustic impedance Z (MRayl), I/Q", RB,
     "Z = Z_Si (1 + r)/(1 - r) with r = -Re(Gamma), Gamma = complex sample/baseline ratio.  Also allows Z > Z_Si, but needs a stable phase."),
    ("z_ratio", "Impedance ratio  Z / Z_Si", "Impedance ratio  Z / Z_Si", RB, "(1 - R)/(1 + R): 0 = air, 1 = as stiff as silicon."),
    ("magnitude", "Magnitude (V)", "Magnitude (V)", ("ne",), "sqrt((I_echo - I_noecho)^2 + (Q_echo - Q_noecho)^2)."),
    ("mag_change", "Magnitude minus baseline (V)", "Magnitude minus baseline (V)", RB, "Magnitude - baseline magnitude."),
    ("mag_pct", "Magnitude change (%)", "Magnitude change (%)", RB, "(Magnitude / baseline magnitude - 1) x 100."),
    ("phase", "Phase change (deg)", "Phase change (deg)", RB, "Phase - baseline phase, wrapped to +-180 deg; phase = atan2(Q_echo - Q_noecho, I_echo - I_noecho)."),
    ("tof", "Phase shift as time (ps)", "Phase shift as time (ps)", RB, "Phase change / (360 x frequency): the equivalent change in round-trip time."),
    ("I_minus_background", "I - baseline (V)", "I - baseline (V)", ("bgiq",), "Echo I minus the baseline echo I."),
    ("Q_minus_background", "Q - baseline (V)", "Q - baseline (V)", ("bgiq",), "Echo Q minus the baseline echo Q."),
    ("I_minus_noecho", "I - no-echo (V)", "I - no-echo (V)", ("ne",), "Echo I minus no-echo I."),
    ("Q_minus_noecho", "Q - no-echo (V)", "Q - no-echo (V)", ("ne",), "Echo Q minus no-echo Q."),
    ("I_raw", "I raw (V)", "I (V)", (), "Echo I as stored."),
    ("Q_raw", "Q raw (V)", "Q (V)", (), "Echo Q as stored."),
]
VAR = {v[0]: v for v in VARS}

REFERENCE_Z = [("Air", "0.0004"), ("Water", "1.48"), ("Fat", "1.35"), ("Blood", "1.66"), ("Muscle", "1.7"),
               ("Skin / soft tissue", "1.5 - 2.0"), ("PDMS", "1.0 - 1.1"), ("Epoxy / photoresist (SU-8)", "~3"),
               ("PMMA", "3.2"), ("Bone (cortical)", "4 - 8"), ("Silicon dioxide", "~13"), ("Aluminium", "17"),
               ("Silicon (Z_Si)", "19.6")]

CMAPS = [("Spectral", "Spectral"), ("Magma", "magma"), ("Viridis", "viridis"), ("Inferno", "inferno"), ("Plasma", "plasma"),
         ("Turbo", "turbo"), ("Jet", "jet"), ("Black & white", "gray"),
         ("Black to green", "#000000,#00ff00"), ("Black to red", "#000000,#ff0000"),
         ("Green - black - red", "#00ff00,#000000,#ff0000"), ("Blue - white - red", "#2166ac,#f7f7f7,#b2182b")]
CMAP = dict(CMAPS)
CLIM_MODES = ["Same for all frames (percentiles)", "Each frame on its own (percentiles)", "Manual min / max"]
FORMATS = ["mp4", "avi", "gif"]

_FALLBACK_STOPS = {
    "magma": ["#000004", "#1c1044", "#4f127b", "#812581", "#b5367a", "#e55064", "#fb8761", "#fec287", "#fcfdbf"],
    "viridis": ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725"],
    "Spectral": ["#9e0142", "#d53e4f", "#f46d43", "#fdae61", "#fee08b", "#e6f598", "#abdda4", "#66c2a5", "#3288bd", "#5e4fa2"],
    "jet": ["#000080", "#0000ff", "#00ffff", "#ffff00", "#ff0000", "#800000"],
    "gray": ["#000000", "#ffffff"],
}
_BASIC = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#00ff00", "blue": "#0000ff", "yellow": "#ffff00",
          "cyan": "#00ffff", "magenta": "#ff00ff", "gray": "#808080", "grey": "#808080", "orange": "#ff8000"}


# ---------------------------------------------------------------------------------------------------------------------
# reading the .dat files
# ---------------------------------------------------------------------------------------------------------------------
DATA_FORMATS = ["Auto-detect", "float32", "float64", "int16", "uint16", "int32", "uint32", "text"]
_DT = {"float32": "f4", "float64": "f8", "int16": "i2", "uint16": "u2", "int32": "i4", "uint32": "u4"}
TIME_SOURCES = ["File time stamps", "Fitted frame rate", "Manual frame rate"]
FRAME_RE = re.compile(r"^(no[-_ ]?echo|echo)[-_ ]([iq])[-_ ](\d+)(?:[-_ ].*)?\.dat$", re.I)
AIR_RE = re.compile(r"^air[-_ ]?(no[-_ ]?echo|echo)[-_ ]?([iq])\.dat$", re.I)


class Fmt:
    """How one .dat file is stored: binary dtype + header bytes, or text; always an h x w image."""

    def __init__(self, kind, dtype, header, h, w, desc):
        self.kind, self.dtype, self.header, self.h, self.w, self.desc = kind, dtype, int(header), int(h), int(w), desc


def _parse_text(txt):
    vals = []
    for line in txt.splitlines():
        toks = line.replace(",", " ").replace(";", " ").split()
        if not toks:
            continue
        try:
            vals.extend(float(t) for t in toks)
        except ValueError:
            continue                                            # a header line
    return np.array(vals, dtype=np.float64)


def _looks_text(b):
    if not b or b"\x00" in b:
        return False
    ok = sum(1 for c in b if c in b" \t\r\n,;.-+eE0123456789")
    return ok / len(b) >= 0.97


def read_dat(path, fmt):
    """One frame as float32, shape (h, w)."""
    n = fmt.h * fmt.w
    if fmt.kind == "text":
        with open(path, "r", errors="ignore") as f:
            vals = _parse_text(f.read())
        if vals.size != n:
            raise ValueError(f"{os.path.basename(path)}: found {vals.size} numbers, expected {n} ({fmt.h} x {fmt.w})")
        return vals.reshape(fmt.h, fmt.w).astype(np.float32)
    a = np.fromfile(path, dtype=fmt.dtype, count=n, offset=fmt.header)
    if a.size != n:
        raise ValueError(f"{os.path.basename(path)}: found {a.size} values after {fmt.header} header bytes, expected {n} ({fmt.h} x {fmt.w}) - "
                         "check the format / image size")
    return a.reshape(fmt.h, fmt.w).astype(np.float32)


def _float_spread(a):
    """Decade spread of |a| for a plausible float interpretation, None when it is clearly garbage."""
    if not np.isfinite(a).all():
        return None
    nz = np.abs(a[a != 0])
    if nz.size == 0:
        return 0.0
    med = float(np.median(nz))
    if med < 1e-12 or med > 1e9:
        return None
    return float(np.std(np.log10(nz)))


def _choose_dtype(data, bps):
    """Pick the dtype of a raw pixel block of `bps` bytes per value."""
    if bps in (4, 8):
        code = "f%d" % bps
        best = None
        for e in "<>":
            a = np.frombuffer(data, dtype=e + code)
            sp = _float_spread(a)
            if sp is not None and (best is None or sp < best[0]):
                best = (sp, e)
        if best is not None:
            return np.dtype(best[1] + code)
        ic = "i%d" % bps
        cand = [(float(np.percentile(np.abs(np.frombuffer(data, dtype=e + ic).astype(np.float64)), 99)), e) for e in "<>"]
        return np.dtype(min(cand)[1] + ic)
    best = None                                                  # 2 bytes: int16 / uint16, either byte order
    for order, (e, c) in enumerate((("<", "u2"), ("<", "i2"), (">", "u2"), (">", "i2"))):
        sd = float(np.std(np.frombuffer(data, dtype=e + c).astype(np.float64)))
        if best is None or sd < 0.7 * best[0]:
            best = (sd, e + c)
    return np.dtype(best[1])


def _dtype_text(dt):
    return f"{dt.name}, {'little' if dt.byteorder in '<=|' else 'big'}-endian"


def detect_format(path, size=128, header=None):
    """Work out the storage format of one file (an air frame).  `size` = expected pixels per side, `header` = forced header bytes."""
    with open(path, "rb") as f:
        raw = f.read()
    S = len(raw)
    if S == 0:
        raise ValueError(f"{os.path.basename(path)} is empty")
    if _looks_text(raw[:8192]):
        cnt = _parse_text(raw.decode("ascii", "ignore")).size
        side = size if size * size == cnt else int(round(cnt ** 0.5))
        if side * side != cnt:
            raise ValueError(f"{os.path.basename(path)} is a text file with {cnt} numbers, which is not a {size} x {size} image")
        return Fmt("text", None, 0, side, side, f"text, {side} x {side} numbers")
    N = size * size
    cands = []
    for order, bps in enumerate((4, 8, 2)):
        hdr = S - N * bps
        if hdr == 0 or (0 < hdr <= 8192 and header in (None, hdr)):
            cands.append((hdr, order, bps, size, size))
    if not cands:
        for order, bps in enumerate((4, 8, 2)):
            if S % bps == 0:
                c = S // bps
                side = int(round(c ** 0.5))
                if side * side == c and header in (None, 0):
                    cands.append((0, order, bps, side, side))
    if not cands:
        raise ValueError(f"{os.path.basename(path)} has {S} bytes, which does not fit a {size} x {size} image with 2, 4 or 8 bytes per pixel "
                         "(header up to 8192 bytes).  Set the data format and header by hand, or use 'Inspect file...'.")
    hdr, _, bps, h, w = sorted(cands)[0]
    dt = _choose_dtype(raw[hdr:hdr + h * w * bps], bps)
    desc = f"{_dtype_text(dt)}, {hdr} header bytes, {h} x {w} pixels"
    return Fmt("bin", dt, hdr, h, w, desc)


def make_format(spec, path):
    """Format for the run: auto-detected from `path`, or built from the chosen name / byte order / header / size."""
    if spec.name == "Auto-detect":
        f = detect_format(path, spec.size, spec.header)
        f.desc += "  (auto-detected)"
        return f
    if spec.name == "text":
        return Fmt("text", None, 0, spec.size, spec.size, f"text, {spec.size} x {spec.size} numbers")
    dt = np.dtype(("<" if spec.endian == "little" else ">") + _DT[spec.name])
    hdr = 0 if spec.header is None else spec.header
    need = hdr + spec.size * spec.size * dt.itemsize
    have = os.path.getsize(path)
    if have != need:
        extra = have - need
        hint = (f"  The file has {extra} bytes more than the pixels need - maybe a header of {hdr + extra} bytes?  (Header bytes = {hdr + extra})"
                if extra > 0 else "  Check the data format and image size.")
        raise ValueError(f"{os.path.basename(path)} has {have} bytes but {spec.size} x {spec.size} {spec.name} with {hdr} header bytes needs {need}." + hint)
    return Fmt("bin", dt, hdr, spec.size, spec.size, f"{_dtype_text(dt)}, {hdr} header bytes, {spec.size} x {spec.size} pixels (set by hand)")


def inspect_file(path, size=128):
    """Lines describing what is inside a .dat file (for the log)."""
    out = []
    S = os.path.getsize(path)
    with open(path, "rb") as f:
        raw = f.read()
    out.append(f"{os.path.basename(path)}: {S} bytes   ({S / (size * size):.3f} bytes per pixel for {size} x {size})")
    out.append("  first 32 bytes: " + " ".join(f"{b:02x}" for b in raw[:32]))
    if _looks_text(raw[:8192]):
        v = _parse_text(raw.decode("ascii", "ignore"))
        out.append(f"  looks like TEXT: {v.size} numbers, first: {np.array2string(v[:6], precision=5)}")
    else:
        for bps, codes in ((4, ("<f4", ">f4", "<i4")), (8, ("<f8", ">f8")), (2, ("<u2", "<i2", ">u2"))):
            hdr = S - size * size * bps
            if hdr < 0 or hdr > 8192:
                continue
            blk = raw[hdr:hdr + size * size * bps]
            out.append(f"  as {bps} bytes/pixel, {hdr} header bytes:")
            for c in codes:
                a = np.frombuffer(blk, dtype=c)
                with np.errstate(all="ignore"):
                    out.append(f"     {c}: first {np.array2string(a[:5].astype(np.float64), precision=5)}   median |x| = {np.median(np.abs(a.astype(np.float64))):.4g}")
    try:
        out.append("  detected: " + detect_format(path, size).desc)
    except Exception as e:
        out.append(f"  detection failed: {e}")
    return out


class FileArray:
    """Frames stored one per file, looked up lazily like an (N, h, w) array (small cache of recent frames)."""

    def __init__(self, paths, fmt, cache=96):
        self.paths, self.fmt, self.cap = list(paths), fmt, cache
        self.shape = (len(self.paths), fmt.h, fmt.w)
        self._c = OrderedDict()

    def __len__(self):
        return len(self.paths)

    def _get(self, i):
        a = self._c.get(i)
        if a is None:
            a = read_dat(self.paths[i], self.fmt)
            self._c[i] = a
            if len(self._c) > self.cap:
                self._c.popitem(last=False)
        else:
            self._c.move_to_end(i)
        return a

    def __getitem__(self, k):
        n = len(self.paths)
        if isinstance(k, slice):
            idx = range(*k.indices(n))
            if len(idx) == 0:
                return np.empty((0, self.fmt.h, self.fmt.w), np.float32)
            return np.stack([self._get(i) for i in idx])
        k = int(k)
        if k < 0:
            k += n
        if not 0 <= k < n:
            raise IndexError(k)
        return self._get(k)


# ---------------------------------------------------------------------------------------------------------------------
# loading one run
# ---------------------------------------------------------------------------------------------------------------------
class RunBase:
    def has(self, what):
        bg = self.bg or {}
        return {"ne": self.ni is not None or "noecho_i" in bg,
                "bgiq": "echo_i" in bg and "echo_q" in bg,
                "bgne": "noecho_i" in bg and "noecho_q" in bg}[what]

    def unavailable_reason(self, key):
        names = {"ne": "no-echo frames", "bgiq": "the air baseline (air-echo-I/Q.dat)", "bgne": "the air no-echo baseline (air-noecho-I/Q.dat)"}
        miss = [names[w] for w in VAR[key][3] if not self.has(w)]
        return "needs " + " and ".join(miss) if miss else None

    def available_vars(self):
        return [v[0] for v in VARS if self.unavailable_reason(v[0]) is None]


def _scan(folder, max_depth=1):
    """All .dat files below `folder` (at most max_depth sub-folder levels), as (path, basename)."""
    base = os.path.abspath(folder).rstrip("\\/").count(os.sep)
    out = []
    for root, dirs, files in os.walk(folder):
        if root.rstrip("\\/").count(os.sep) - base >= max_depth:
            dirs[:] = []
        for fn in sorted(files):
            if fn.lower().endswith(".dat"):
                out.append((os.path.join(root, fn), fn))
    return out


def find_runs(path):
    """Sub-folders of `path` that contain MEG2 frame files (used for the 'choose one of these' hint)."""
    out = []
    try:
        for d in sorted(os.listdir(path)):
            p = os.path.join(path, d)
            if os.path.isdir(p) and any(FRAME_RE.match(fn) for _, fn in _scan(p)):
                out.append(p)
    except OSError:
        pass
    return out


def _norm_kind(s):
    return "noecho" if s.lower().startswith("no") else "echo"


class Run2(RunBase):
    """One MEG2 run folder: air baseline + echo / no-echo frames (one .dat file per frame, read on demand)."""

    def __init__(self, folder, spec, log=None, progress=None, cancel=None):
        log = log or (lambda m: None)
        progress = progress or (lambda f: None)
        self.folder = os.path.abspath(folder)
        self.name = os.path.basename(self.folder.rstrip("\\/"))
        if not os.path.isdir(self.folder):
            raise FileNotFoundError(f"Folder not found: {folder}")
        self.meta = {}
        log("Scanning " + self.folder)
        frames, air, dup = {}, {}, 0
        for path, fn in _scan(self.folder):
            m = FRAME_RE.match(fn)
            if m:
                key = (_norm_kind(m.group(1)), m.group(2).upper())
                d = frames.setdefault(key, {})
                n = int(m.group(3))
                if n in d:
                    dup += 1
                else:
                    d[n] = path
                continue
            m = AIR_RE.match(fn)
            if m:
                air.setdefault((_norm_kind(m.group(1)), m.group(2).upper()), path)
        if not frames:
            subs = find_runs(self.folder)
            hint = ("  This folder contains run folders - choose one of them:  " + ",  ".join(os.path.basename(x) for x in subs[:8])) if subs else \
                "  Expected files like echo/echo_I_1_o.dat and no-echo/noecho_Q_1_o.dat inside the timestamp folder."
            raise FileNotFoundError("No frame files (echo_I_<n>_*.dat ...) found in this folder." + hint)
        self.note = ""
        if dup:
            self.note = f"{dup} duplicate frame numbers (same n, different suffix) - the first file of each was used."
        keys = [("echo", "I"), ("echo", "Q"), ("noecho", "I"), ("noecho", "Q")]
        counts = {k: len(frames.get(k, {})) for k in keys}
        log("  frames found:  echo I %d, echo Q %d, no-echo I %d, no-echo Q %d" % tuple(counts[k] for k in keys))
        if min(counts.values()) == 0:
            raise FileNotFoundError("Frame files are missing for: " + ", ".join(f"{k[0]} {k[1]}" for k in keys if counts[k] == 0)
                                    + ".  Both echo and no-echo, I and Q, are needed.")
        common = sorted(set.intersection(*[set(frames[k]) for k in keys]))
        if len(common) < 2:
            raise ValueError("Fewer than 2 frame numbers exist in all four sets (echo I/Q, no-echo I/Q).")
        if len(common) < max(counts.values()):
            self.note += f"  {max(counts.values()) - len(common)} frames have no complete echo/no-echo I/Q set and are skipped."
        gaps = int(common[-1] - common[0] + 1 - len(common))
        if gaps:
            self.note += f"  frame numbers have {gaps} gaps."
        self.frame_numbers = np.array(common)
        # ---- format
        probe = air.get(("echo", "I")) or frames[("echo", "I")][common[0]]
        self.fmt = make_format(spec, probe)
        log(f"  data format: {self.fmt.desc}   (from {os.path.basename(probe)})")
        self.h, self.w = self.fmt.h, self.fmt.w
        for k in keys:                                           # every kind of file must read with this format
            read_dat(frames[k][common[0]], self.fmt)
        # ---- arrays
        paths = {k: [frames[k][n] for n in common] for k in keys}
        self.ei, self.eq = FileArray(paths[("echo", "I")], self.fmt), FileArray(paths[("echo", "Q")], self.fmt)
        self.ni, self.nq = FileArray(paths[("noecho", "I")], self.fmt), FileArray(paths[("noecho", "Q")], self.fmt)
        self.arrs = [self.ei, self.eq, self.ni, self.nq]
        self.n = len(common)
        # ---- air baseline
        self.bg, self.bg_note = None, ""
        akeys = {("echo", "I"): "echo_i", ("echo", "Q"): "echo_q", ("noecho", "I"): "noecho_i", ("noecho", "Q"): "noecho_q"}
        if all(k in air for k in akeys):
            try:
                self.bg = {nm: read_dat(air[k], self.fmt).astype(np.float64) for k, nm in akeys.items()}
            except ValueError as e:
                self.bg_note = "air files could not be read with this format: " + str(e)
        else:
            self.bg_note = "air files missing: " + ", ".join(f"air-{k[0]}-{k[1]}" for k in akeys if k not in air)
        # ---- time stamps (modification times of the files)
        files = paths
        t = np.zeros(self.n)
        for i in range(self.n):
            try:
                t[i] = 0.5 * (os.path.getmtime(files[("echo", "I")][i]) + os.path.getmtime(files[("echo", "Q")][i]))
            except OSError:
                t[i] = np.nan
            if cancel is not None and cancel.is_set():
                raise Cancelled()
        self.t_stamp = t
        self.stamp_note = ""
        self.stamp_bad = False
        dt = np.diff(t)
        if not np.isfinite(t).all() or t[-1] - t[0] < 1e-3 or np.mean(dt <= 0) > 0.2:
            self.stamp_bad = True
            self.stamp_note = ("the file time stamps are identical or not increasing (the files were probably copied) - "
                               "set the frame rate by hand (Time from: Manual frame rate)")
        else:
            cv = float(np.std(dt) / np.mean(dt))
            self.stamp_note = f"time-stamp interval {np.mean(dt) * 1000:.1f} ms, scatter {cv * 100:.0f}% of the interval"
            if cv > 0.3:
                self.stamp_note += "  (irregular: 'Fitted frame rate' gives a smoother time axis)"
        self.freq_mhz = 0.0
        self.pitch_um = PIXEL_PITCH_UM
        self.et = t.copy()
        self.fps = float("nan")
        self.set_time_mode(TIME_SOURCES[0] if not self.stamp_bad else TIME_SOURCES[2], 1.0)
        progress(1.0)

    def set_time_mode(self, mode, manual_fps=1.0):
        idx = np.arange(self.n, dtype=np.float64)
        if mode == TIME_SOURCES[0] and not self.stamp_bad:
            et = self.t_stamp.copy()
        elif mode == TIME_SOURCES[1] and not self.stamp_bad:
            a, b = np.polyfit(idx, self.t_stamp, 1)
            et = a * idx + b
        else:
            et = idx / max(manual_fps, 1e-9)
        self.et = et
        dur = float(et[-1] - et[0])
        self.fps = (self.n - 1) / dur if dur > 0 else float("nan")


# ---------------------------------------------------------------------------------------------------------------------
# averaging and variables
# ---------------------------------------------------------------------------------------------------------------------
def _mean_slice(a, lo, hi, chunk=64):
    acc = np.zeros(a.shape[1:], np.float64)
    for s in range(lo, hi, chunk):
        acc += np.asarray(a[s:min(hi, s + chunk)], dtype=np.float64).sum(axis=0)
    return acc / max(1, hi - lo)


def _noecho_fill(run):
    bg = run.bg or {}
    return [bg.get("noecho_i"), bg.get("noecho_q")] if run.ni is None else []


def window_mean(run, lo, k):
    """Mean of raw frames lo..k (inclusive) -> [Ie, Qe, Ine, Qne]."""
    out = [_mean_slice(a, lo, k + 1) for a in run.arrs]
    return out + _noecho_fill(run)


def iter_windows(run, avg, lo_bound, ks):
    """Yield (k, [Ie, Qe, Ine, Qne]) for the window ends in `ks` (ascending).  A window covers frames max(lo_bound, k-avg+1)..k.
    Small steps use running sums (one add + one subtract per frame, rebuilt exactly every 2000 frames), large steps read each window."""
    ks = list(ks)
    if not ks:
        return
    step = ks[1] - ks[0] if len(ks) > 1 else 1
    if step >= avg:
        for k in ks:
            yield k, window_mean(run, max(lo_bound, k - avg + 1), k)
        return
    first = max(lo_bound, ks[0] - avg + 1)
    sums = [np.zeros((run.h, run.w)) for _ in run.arrs]
    j, since = 0, 0
    for k in range(first, ks[-1] + 1):
        for s, a in zip(sums, run.arrs):
            s += a[k]
            if k - avg >= first:
                s -= a[k - avg]
        since += 1
        if since >= 2000:
            lo = max(first, k - avg + 1)
            sums = [_mean_slice(a, lo, k + 1) * (k + 1 - lo) for a in run.arrs]
            since = 0
        if k == ks[j]:
            m = min(avg, k - first + 1)
            yield k, [s / m for s in sums] + _noecho_fill(run)
            j += 1
            if j >= len(ks):
                return


def wrap_deg(x):
    return (x + 180.0) % 360.0 - 180.0


def derive(variable, win, run, zsi):
    Ie, Qe, Ine, Qne = win
    bg = run.bg or {}
    if variable == "I_raw":
        return Ie
    if variable == "Q_raw":
        return Qe
    if variable == "I_minus_background":
        return Ie - bg["echo_i"]
    if variable == "Q_minus_background":
        return Qe - bg["echo_q"]
    if variable == "I_minus_noecho":
        return Ie - Ine
    if variable == "Q_minus_noecho":
        return Qe - Qne
    dI, dQ = Ie - Ine, Qe - Qne
    mag = np.hypot(dI, dQ)
    if variable == "magnitude":
        return mag
    bI, bQ = bg["echo_i"] - bg["noecho_i"], bg["echo_q"] - bg["noecho_q"]
    mag_bg = np.hypot(bI, bQ)
    with np.errstate(divide="ignore", invalid="ignore"):
        R = np.where(mag_bg > 0, mag / mag_bg, np.nan)
        if variable == "reflection":
            return R
        if variable == "refl_db":
            return 20.0 * np.log10(np.maximum(R, 1e-6))
        if variable == "power":
            return R * R
        if variable == "transmit":
            return 1.0 - R * R
        if variable in ("impedance", "z_ratio"):
            Rc = np.clip(R, 0.0, 1.0)
            ratio = (1.0 - Rc) / (1.0 + Rc)
            return ratio if variable == "z_ratio" else zsi * ratio
        if variable == "impedance_iq":
            re_gamma = np.where(mag_bg > 0, (dI * bI + dQ * bQ) / (mag_bg ** 2), np.nan)     # Re[(dI+jdQ)/(bI+jbQ)]
            r = np.clip(-re_gamma, -1.0, 0.95)
            return zsi * (1.0 + r) / (1.0 - r)
        if variable == "magnitude_minus_background" or variable == "mag_change":
            return mag - mag_bg
        if variable == "mag_pct":
            return (R - 1.0) * 100.0
        if variable in ("phase", "tof"):
            ph = wrap_deg(np.degrees(np.arctan2(dQ, dI)) - np.degrees(np.arctan2(bQ, bI)))
            return ph if variable == "phase" else ph / (360.0 * run.freq_mhz * 1e6) * 1e12
    raise ValueError(variable)


def _conv_axis(a, k, axis):
    r = len(k) // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    n = a.shape[axis]
    out = 0.0
    for i, wgt in enumerate(k):
        sl = [slice(None), slice(None)]
        sl[axis] = slice(i, i + n)
        out = out + wgt * p[tuple(sl)]
    return out


def smooth(img, sigma):
    """Gaussian smoothing (sigma in pixels), edges replicated; non-finite pixels are filled with the median first."""
    if sigma <= 0:
        return img
    ok = np.isfinite(img)
    if not ok.all():
        img = np.where(ok, img, np.median(img[ok]) if ok.any() else 0.0)
    r = max(1, int(3 * sigma + 0.5))
    x = np.arange(-r, r + 1)
    k = np.exp(-x ** 2 / (2.0 * sigma ** 2))
    k /= k.sum()
    return _conv_axis(_conv_axis(img, k, 0), k, 1)


def orient(img, o):
    """Rotate (counter-clockwise, multiples of 90 deg) and flip the finished image; applied last so it never changes the numbers."""
    rot = int(getattr(o, "rot", 0)) % 360
    if rot:
        img = np.rot90(img, rot // 90)
    if getattr(o, "flipx", False):
        img = img[:, ::-1]
    if getattr(o, "flipy", False):
        img = img[::-1, :]
    return np.ascontiguousarray(img)


def process(run, o, win):
    return orient(smooth(derive(o.variable, win, run, o.zsi), o.smooth), o)


def subtract_ref(o, img, ref):
    if ref is None:
        return img
    d = img - ref
    return wrap_deg(d) if o.variable == "phase" else d


def image_at(run, o, k, ref):
    """The processed image for the window ending at raw frame k (0-based)."""
    win = window_mean(run, max(o.start0, k - o.avg + 1), k)
    return subtract_ref(o, process(run, o, win), ref)


def reference_image(run, o):
    if o.ref_frame is None:
        return None
    k = o.ref_frame
    return process(run, o, window_mean(run, max(0, k - o.avg + 1), k))


def frame_list(run, o):
    first = o.start0 if o.partial else o.start0 + o.avg - 1
    return list(range(first, o.end0 + 1, o.step))


def percentile_limits(img, plo, phi):
    v = img[np.isfinite(img)]
    if v.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(v, [plo, phi])
    return float(lo), float(hi)


def global_limits(run, o, ks, ref, log=None, cancel=None):
    """Colour limits that are used for EVERY frame: percentiles over frames sampled across the video."""
    if o.clim_mode == "manual":
        return o.vmin, o.vmax
    sample = ks[::max(1, len(ks) // 150)]
    if sample[-1] != ks[-1]:
        sample = sample + [ks[-1]]
    vals = []
    rng = np.random.default_rng(0)
    for i, k in enumerate(sample):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        v = image_at(run, o, k, ref)
        v = v[np.isfinite(v)].ravel()
        if v.size > 40000:
            v = rng.choice(v, 40000, replace=False)
        vals.append(v)
    allv = np.concatenate(vals) if vals else np.array([0.0, 1.0])
    lo, hi = (float(x) for x in np.percentile(allv, [o.plo, o.phi]))
    if log:
        log(f"Colour limits {lo:.4g} .. {hi:.4g}   ({o.plo:g}-{o.phi:g} percentile of {len(sample)} frames sampled over the video; same for every frame)")
    return lo, hi


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# colours and drawing (PIL only)
# ---------------------------------------------------------------------------------------------------------------------
def _hex_to_rgb(c):
    c = c.strip()
    c = _BASIC.get(c.lower(), c)
    if c.startswith("#") and len(c) == 7:
        return [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    try:
        import matplotlib.colors as mc
        return [int(round(255 * x)) for x in mc.to_rgb(c)]
    except Exception:
        raise ValueError(f"unknown colour '{c}'")


def _lut_from_stops(stops):
    pts = np.array([_hex_to_rgb(s) for s in stops], float)
    x = np.linspace(0, 1, 256)
    xp = np.linspace(0, 1, len(pts))
    return np.stack([np.interp(x, xp, pts[:, c]) for c in range(3)], 1).round().astype(np.uint8)


def make_lut(spec, reverse=False):
    """spec: a matplotlib colormap name, or colours separated by commas ('black,cyan,white' or '#000000,#00ff00')."""
    spec = spec.strip()
    if "," in spec:
        lut = _lut_from_stops(spec.split(","))
    else:
        lut = None
        try:
            import matplotlib
            cm = matplotlib.colormaps[spec]
            lut = (np.asarray(cm(np.linspace(0, 1, 256))[:, :3]) * 255).round().astype(np.uint8)
        except ImportError:
            base = spec[:-2] if spec.endswith("_r") else spec
            if base in _FALLBACK_STOPS:
                lut = _lut_from_stops(_FALLBACK_STOPS[base])
                lut = lut[::-1] if spec.endswith("_r") else lut
            else:
                raise ValueError(f"colormap '{spec}' needs matplotlib (pip install matplotlib); without it use one of: "
                                 + ", ".join(_FALLBACK_STOPS) + " or colours such as black,cyan,white")
        except KeyError:
            raise ValueError(f"unknown colormap '{spec}' (examples: cividis, hot, gray_r, coolwarm, or colours: black,cyan,white)")
    return lut[::-1].copy() if reverse else lut


def load_font(size):
    from PIL import ImageFont
    for f in FONT_FILES:
        try:
            return ImageFont.truetype(f, size), f
        except OSError:
            continue
    return ImageFont.load_default(), "PIL default"


def nice_ticks(vmin, vmax, n=5):
    span = vmax - vmin
    if not span > 0:
        return [vmin]
    raw = span / (n + 3.0)
    mag = 10 ** np.floor(np.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    first = np.ceil(vmin / step - 1e-9) * step
    ticks = [float(first + i * step) for i in range(int((vmax - first) / step + 1e-9) + 1)]
    return ticks or [vmin, vmax]


def fmt(v):
    s = f"{v:.4g}"
    return "0" if abs(float(s)) < 1e-12 else s


def _text(d, xy, text, font, fill="white", anchor="ls"):
    try:
        d.text(xy, text, font=font, fill=fill, anchor=anchor)
    except ValueError:
        d.text(xy, text, font=font, fill=fill)


class Painter:
    """Draws one video frame: title and variable on top, map + colour bar (no side panel), and a footer with
    FOV, averaged frames and time."""

    def __init__(self, run, o, layout_limits):
        from PIL import Image, ImageDraw
        self.Image, self.ImageDraw = Image, ImageDraw
        P = int(o.image_px)
        s = P / 560.0

        def sz(x):
            return max(8, int(round(x * s)))
        self.lut = make_lut(o.cmap_spec, o.reverse)
        f_tick, fpath = load_font(sz(20))
        self.f_tick = f_tick
        self.font_name = os.path.basename(fpath)
        h, w = run.h, run.w
        if int(getattr(o, "rot", 0)) % 180:
            h, w = w, h
        sc = P / max(h, w)
        self.img_w, self.img_h = max(2, int(round(w * sc))), max(2, int(round(h * sc)))
        self.resample = Image.NEAREST if max(h, w) <= 64 else Image.BILINEAR
        # --- width: the map starts at the left edge and the colour-bar labels end at the right edge (no side margins)
        gap, self.bar_w, tgap, pad_r = sz(10), sz(22), sz(10), sz(4)
        lo, hi = layout_limits
        labels = [fmt(v) for v in nice_ticks(lo, hi)] + ["-0.00"]
        tick_w = int(max(f_tick.getlength(t) for t in labels))
        W = self.img_w + gap + self.bar_w + 2 + tgap + tick_w + pad_r
        W += W % 2
        self.x_img = 0
        self.x_bar = self.img_w + gap
        self.x_lab = self.x_bar + self.bar_w + 2 + tgap
        mt = sz(5)                                               # text inset from the edge

        def fit(text, size, max_w):                              # longest text shrinks to fit the width
            while True:
                f = load_font(size)[0]
                if f.getlength(text or " ") <= max_w or size <= 10:
                    return f
                size -= 1
        self.f_title = fit(o.title, sz(46), W - 2 * mt)
        self.f_sub = fit(o.label, sz(26), W - 2 * mt)
        fov_txt = f"FOV  {w * run.pitch_um / 1000.0:.2f} x {h * run.pitch_um / 1000.0:.2f} mm\u00b2"
        avg_txt = f"Averaged frames: {o.avg}"
        lab_size = sz(22)
        while lab_size > 10:
            f = load_font(lab_size)[0]
            if f.getlength(fov_txt) + f.getlength(avg_txt) + sz(24) <= W - 2 * mt:
                break
            lab_size -= 1
        self.f_lab = load_font(lab_size)[0]
        self.f_val = load_font(int(round(lab_size * 1.27)))[0]   # the running time, slightly larger

        def height(font):
            a, d = font.getmetrics() if hasattr(font, "getmetrics") else (font.size, 0)
            return a, d
        ta, td = height(self.f_title)
        sa, sd = height(self.f_sub)
        la, ld = height(self.f_lab)
        va, vd = height(self.f_val)
        y = sz(8)
        self.y_title = y + ta
        y += ta + td + sz(2)
        self.y_sub = y + sa
        y += sa + sd + sz(12)
        self.y_img = y
        self.pad_bar = sz(10)
        y_foot = y + self.img_h + sz(12)
        self.y_rule = y_foot
        self.y_row1 = y_foot + sz(10) + la
        self.y_row2 = self.y_row1 + ld + sz(8) + va
        H = self.y_row2 + vd + sz(8)
        self.W, self.H = W, H + H % 2
        self.t_x = mt + int(self.f_lab.getlength("Time")) + sz(10)
        base = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        d = ImageDraw.Draw(base)
        _text(d, (mt, self.y_title), o.title, self.f_title)
        _text(d, (mt, self.y_sub), o.label, self.f_sub)
        d.line([0, self.y_rule, self.W, self.y_rule], fill=(90, 90, 90))
        _text(d, (mt, self.y_row1), fov_txt, self.f_lab)
        _text(d, (self.W - mt, self.y_row1), avg_txt, self.f_lab, anchor="rs")
        _text(d, (mt, self.y_row2), "Time", self.f_lab)
        self.base = base
        self._bar_key, self._bar_img = None, None

    def _bar(self, vmin, vmax):
        key = (round(vmin, 12), round(vmax, 12))
        if key == self._bar_key:
            return self._bar_img
        Image, ImageDraw = self.Image, self.ImageDraw
        pb = self.pad_bar
        wb = self.W - self.x_bar
        im = Image.new("RGB", (wb, self.img_h + 2 * pb), (0, 0, 0))
        d = ImageDraw.Draw(im)
        grad = np.linspace(255, 0, self.img_h).round().astype(np.uint8)
        im.paste(Image.fromarray(self.lut[np.repeat(grad[:, None], self.bar_w, axis=1)]), (1, pb))
        d.rectangle([0, pb - 1, self.bar_w + 1, pb + self.img_h], outline="white")
        for v in nice_ticks(vmin, vmax):
            y = pb + self.img_h - 1 - int(round((v - vmin) / (vmax - vmin) * (self.img_h - 1)))
            d.line([self.bar_w + 1, y, self.bar_w + 7, y], fill="white")
            _text(d, (self.x_lab - self.x_bar + 1, y), fmt(v), self.f_tick, anchor="lm")
        self._bar_key, self._bar_img = key, im
        return im

    def frame(self, img, t_s, vmin, vmax):
        if not vmax > vmin:
            vmax = vmin + 1e-12
        u8 = np.clip((np.nan_to_num(img, nan=vmin) - vmin) / (vmax - vmin) * 255.0, 0, 255).astype(np.uint8)
        pic = self.Image.fromarray(self.lut[u8]).resize((self.img_w, self.img_h), self.resample)
        fr = self.base.copy()
        fr.paste(pic, (self.x_img, self.y_img))
        fr.paste(self._bar(vmin, vmax), (self.x_bar, self.y_img - self.pad_bar))
        d = self.ImageDraw.Draw(fr)
        _text(d, (self.t_x, self.y_row2), f"{t_s:.2f} s", self.f_val)
        return fr


# ---------------------------------------------------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------------------------------------------------
def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _encoders(exe):
    try:
        r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return r.stdout
    except Exception:
        return ""


class Writer:
    """Pipes RGB frames into ffmpeg (mp4 = H.264, avi = MPEG-4, gif = palette GIF).  Without ffmpeg only GIF is possible."""

    def __init__(self, path, W, H, fps, fmt_):
        self.path, self.W, self.H, self.fps, self.fmt = path, W, H, float(fps), fmt_
        self.exe = ffmpeg_exe()
        self.p, self.frames, self.err = None, [], None
        if self.exe is None:
            if fmt_ != "gif":
                raise RuntimeError("ffmpeg was not found, so mp4 / avi cannot be written.  Click 'Install ffmpeg' (or: pip install imageio-ffmpeg).  GIF works without it.")
            return
        cmd = [self.exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:g}", "-i", "-", "-an"]
        if fmt_ == "mp4":
            enc = _encoders(self.exe)
            cmd += (["-c:v", "libx264", "-preset", "medium", "-crf", "17"] if "libx264" in enc else ["-c:v", "mpeg4", "-q:v", "2"])
            cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        elif fmt_ == "avi":
            cmd += ["-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-vf", "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3", "-loop", "0"]
        cmd += [path]
        self.err = tempfile.TemporaryFile()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self.err,
                                  creationflags=0x08000000 if os.name == "nt" else 0)

    def add(self, im):
        if self.p is not None:
            try:
                self.p.stdin.write(im.tobytes())
            except (BrokenPipeError, OSError):
                raise RuntimeError("ffmpeg stopped: " + self._err_text())
        else:
            self.frames.append(im.convert("P", palette=1))

    def _err_text(self):
        try:
            self.err.seek(0)
            return self.err.read().decode(errors="replace")[-500:]
        except Exception:
            return ""

    def close(self):
        if self.p is not None:
            try:
                self.p.stdin.close()
            except Exception:
                pass
            self.p.wait()
            if self.p.returncode:
                raise RuntimeError("ffmpeg failed: " + self._err_text())
            self.err.close()
        elif self.frames:
            self.frames[0].save(self.path, save_all=True, append_images=self.frames[1:], duration=max(10, int(1000 / self.fps)), loop=0)
        return self.path

    def abort(self):
        try:
            if self.p is not None:
                self.p.stdin.close()
                self.p.kill()
                self.p.wait()
        except Exception:
            pass
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------------------------------
# jobs (run in a worker thread; they only talk to the GUI through `log` / `progress`)
# ---------------------------------------------------------------------------------------------------------------------
def _layout_limits(run, o, ks, ref, lims):
    if lims is not None:
        return lims
    sample = ks[::max(1, len(ks) // 12)][:12]            # per-frame mode: the widest tick labels of a few frames
    lo, hi = [], []
    for k in sample:
        a, b = percentile_limits(image_at(run, o, k, ref), o.plo, o.phi)
        lo.append(a)
        hi.append(b)
    return min(lo), max(hi)


def _limits_for(run, o, ks, ref, cache, log, cancel):
    """(vmin, vmax) for all frames, or None for per-frame mode.  Cached while the settings do not change."""
    if o.clim_mode == "frame":
        return None
    key = (run.folder, o.variable, o.avg, o.smooth, o.ref_frame, o.start0, o.end0, o.step, o.partial, o.zsi, o.clim_mode,
           o.plo, o.phi, o.vmin, o.vmax)
    if cache.get("key") == key:
        return cache["lims"]
    if o.clim_mode == "global":
        log("Computing colour limits ...")
    lims = global_limits(run, o, ks, ref, log, cancel)
    cache["key"], cache["lims"] = key, lims
    return lims


def preview_job(run, o, k, cache, log, cancel):
    ks = frame_list(run, o)
    if not ks:
        raise ValueError("No frames to render: the averaging window is longer than the selected frame range.")
    ref = reference_image(run, o)
    k_eff = min(max(k, ks[0]), ks[-1])
    if k_eff != k:
        log(f"Frame {k + 1} is outside the video (first averaged frame = {ks[0] + 1}, last = {ks[-1] + 1}); showing frame {k_eff + 1}.")
    lims = _limits_for(run, o, ks, ref, cache, log, cancel)
    img = image_at(run, o, k_eff, ref)
    vmin, vmax = lims if lims else percentile_limits(img, o.plo, o.phi)
    painter = Painter(run, o, _layout_limits(run, o, ks, ref, lims))
    t0 = run.et[o.start0] if o.tzero else run.et[0]
    fr = painter.frame(img, run.et[k_eff] - t0, vmin, vmax)
    log(f"Preview: frame {k_eff + 1}  (average of frames {max(o.start0, k_eff - o.avg + 1) + 1} - {k_eff + 1}),  t = {run.et[k_eff] - t0:.2f} s,  limits {vmin:.4g} .. {vmax:.4g},  video size {painter.W} x {painter.H}")
    return fr


def generate_job(run, o, cache, log, progress, cancel):
    t_start = time.time()
    ks = frame_list(run, o)
    if not ks:
        raise ValueError("No frames to render: the averaging window is longer than the selected frame range.")
    ref = reference_image(run, o)
    lims = _limits_for(run, o, ks, ref, cache, log, cancel)
    painter = Painter(run, o, _layout_limits(run, o, ks, ref, lims))
    os.makedirs(o.out_dir, exist_ok=True)
    path = os.path.join(o.out_dir, o.out_name + "." + o.fmt)
    if o.fmt == "gif" and len(ks) > 400:
        log(f"Note: a GIF with {len(ks)} frames gets large; consider a larger 'Every Nth frame', a smaller image size, or mp4.")
    log(f"Writing {path}")
    log(f"  {len(ks)} video frames, {painter.W} x {painter.H} px, {o.vfps:g} frames/s  ->  {len(ks) / o.vfps:.1f} s long   (font: {painter.font_name})")
    writer = Writer(path, painter.W, painter.H, o.vfps, o.fmt)
    t0 = run.et[o.start0] if o.tzero else run.et[0]
    done, last_pct = 0, -1
    try:
        for k, win in iter_windows(run, o.avg, o.start0, ks):
            if cancel.is_set():
                raise Cancelled()
            img = subtract_ref(o, process(run, o, win), ref)
            vmin, vmax = lims if lims else percentile_limits(img, o.plo, o.phi)
            writer.add(painter.frame(img, run.et[k] - t0, vmin, vmax))
            done += 1
            progress(done / len(ks))
            pct = int(100 * done / len(ks))
            if pct >= last_pct + 10 or done == len(ks):
                last_pct = pct
                log(f"  {pct:3d}%   frame {done} / {len(ks)}   {time.time() - t_start:.0f} s")
        log("  finalising file ...")
        writer.close()
    except BaseException:
        writer.abort()
        raise
    log(f"Saved {path}   ({os.path.getsize(path) / 1e6:.1f} MB, {time.time() - t_start:.0f} s)")
    return path


# ---------------------------------------------------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------------------------------------------------
class App:
    PREF_KEYS = ["run_dir", "variable", "avg", "every", "vfps", "partial", "tzero", "smooth", "zsi", "cmap", "cmap_custom",
                 "reverse", "clim_mode", "plo", "phi", "vmin", "vmax", "image_px", "out_dir", "fmt",
                 "dfmt", "endian", "header", "imgsize", "pitch", "unit", "freq", "tsrc", "mfps", "rot", "flipx", "flipy"]

    def __init__(self, root):
        self.root = root
        self.run = None
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.cache = {}
        self.preview_pil = None
        self._photo = None
        self._auto_label = ""
        self._auto_out = ""
        self._auto_name = ""
        self._pref_variable = None
        root.title("MEG2 video maker")
        root.geometry(f"1280x{max(600, min(860, root.winfo_screenheight() - 90))}")
        root.minsize(1100, 700)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._make_vars()
        self._build()
        self._load_prefs()
        self._refresh_ffmpeg()
        self._summary()
        root.after(80, self._poll)
        if START_FOLDER and os.path.isdir(START_FOLDER):
            self.v["run_dir"].set(START_FOLDER)
            root.after(200, self.on_load)

    # ---- variables ---------------------------------------------------------------------------------------------
    def _make_vars(self):
        S = tk.StringVar
        self.v = dict(run_dir=S(), title=S(), label=S(), variable=S(), avg=S(value="10"), start=S(value="1"), end=S(value="1"),
                      every=S(value="1"), vfps=S(value="30"), partial=tk.BooleanVar(value=False), tzero=tk.BooleanVar(value=False),
                      smooth=S(value="0"), ref_on=tk.BooleanVar(value=False), ref_frame=S(value="1"), zsi=S(value=str(Z_SI_MRAYL)),
                      cmap=S(value="Spectral"), cmap_custom=S(), reverse=tk.BooleanVar(value=False), clim_mode=S(value=CLIM_MODES[0]),
                      plo=S(value="1"), phi=S(value="99"), vmin=S(value="0"), vmax=S(value="1"), image_px=S(value="640"),
                      out_dir=S(), out_name=S(), fmt=S(value="mp4"), preview_frame=S(value="1"),
                      dfmt=S(value=DATA_FORMATS[0]), endian=S(value="little"), header=S(value="auto"), imgsize=S(value="128"),
                      pitch=S(value=f"{PIXEL_PITCH_UM:g}"), unit=S(value="V"), freq=S(), tsrc=S(value=TIME_SOURCES[0]), mfps=S(value="1"),
                      rot=S(value="0"), flipx=tk.BooleanVar(value=False), flipy=tk.BooleanVar(value=False))
        self.var_names = {}                                       # menu text -> key
        self.v["run_dir"].trace_add("write", lambda *a: None)

    # ---- layout -----------------------------------------------------------------------------------------------
    def _build(self):
        v = self.v
        root = self.root
        holder = ttk.Frame(root)                                 # left column; scrolls if the screen is too short
        holder.grid(row=0, column=0, sticky="ns")
        try:
            bg = ttk.Style().lookup("TFrame", "background") or root.cget("bg")
        except tk.TclError:
            bg = root.cget("bg")
        cv = tk.Canvas(holder, highlightthickness=0, bd=0, bg=bg, width=10)
        vsb = ttk.Scrollbar(holder, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=vsb.set)
        cv.pack(side="left", fill="y", expand=True)
        left = ttk.Frame(cv, padding=(10, 8, 6, 8))
        cv.create_window(0, 0, window=left, anchor="nw")

        def fit(_e=None):
            cv.configure(scrollregion=(0, 0, left.winfo_reqwidth(), left.winfo_reqheight()), width=left.winfo_reqwidth())
            if left.winfo_reqheight() > cv.winfo_height() + 2:
                vsb.pack(side="right", fill="y")
            else:
                vsb.pack_forget()
                cv.yview_moveto(0)
        left.bind("<Configure>", fit)
        cv.bind("<Configure>", fit)

        def wheel(e):
            if left.winfo_reqheight() > cv.winfo_height() + 2:
                cv.yview_scroll(-1 if (e.num == 4 or e.delta > 0) else 1, "units")
        holder.bind("<Enter>", lambda e: (root.bind_all("<MouseWheel>", wheel), root.bind_all("<Button-4>", wheel), root.bind_all("<Button-5>", wheel)))
        holder.bind("<Leave>", lambda e: (root.unbind_all("<MouseWheel>"), root.unbind_all("<Button-4>"), root.unbind_all("<Button-5>")))
        right = ttk.Frame(root, padding=(6, 8, 10, 8))
        right.grid(row=0, column=1, sticky="nsew")
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self.locked = []

        def add(w, lock=True):
            if lock:
                self.locked.append(w)
            return w

        # -- run ------------------------------------------------------------------------------
        f = ttk.LabelFrame(left, text="Run folder (timestamp) and data files", padding=8)
        f.grid(row=0, column=0, sticky="ew")
        f.columnconfigure(0, weight=1)
        add(ttk.Entry(f, textvariable=v["run_dir"], width=38)).grid(row=0, column=0, sticky="ew")
        add(ttk.Button(f, text="Browse...", command=self.on_browse)).grid(row=0, column=1, padx=(4, 0))
        add(ttk.Button(f, text="Load", command=self.on_load)).grid(row=0, column=2, padx=(4, 0))
        self.info = ttk.Label(f, text="No run loaded.", foreground="#555", wraplength=520, justify="left")
        self.info.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        d = ttk.Frame(f)
        d.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(d, text="Data format").grid(row=0, column=0, sticky="w")
        add(ttk.Combobox(d, textvariable=v["dfmt"], state="readonly", values=DATA_FORMATS, width=11)).grid(row=0, column=1, padx=(4, 10))
        ttk.Label(d, text="Byte order").grid(row=0, column=2)
        add(ttk.Combobox(d, textvariable=v["endian"], state="readonly", values=["little", "big"], width=7)).grid(row=0, column=3, padx=(4, 10))
        ttk.Label(d, text="Header bytes").grid(row=0, column=4)
        add(ttk.Entry(d, textvariable=v["header"], width=6)).grid(row=0, column=5, padx=(4, 0))
        ttk.Label(d, text="Image size (px)").grid(row=1, column=0, sticky="w", pady=(5, 0))
        add(ttk.Entry(d, textvariable=v["imgsize"], width=6)).grid(row=1, column=1, sticky="w", padx=(4, 10), pady=(5, 0))
        ttk.Label(d, text="Pixel pitch (um)").grid(row=1, column=2, pady=(5, 0))
        add(ttk.Entry(d, textvariable=v["pitch"], width=7)).grid(row=1, column=3, sticky="w", padx=(4, 10), pady=(5, 0))
        ttk.Label(d, text="Unit").grid(row=1, column=4, pady=(5, 0))
        add(ttk.Entry(d, textvariable=v["unit"], width=6)).grid(row=1, column=5, sticky="w", padx=(4, 0), pady=(5, 0))
        ttk.Label(d, text="Frequency (MHz)").grid(row=2, column=0, sticky="w", pady=(5, 0))
        add(ttk.Entry(d, textvariable=v["freq"], width=8)).grid(row=2, column=1, sticky="w", padx=(4, 10), pady=(5, 0))
        ttk.Label(d, text="(only for 'Phase shift as time')", foreground="#555").grid(row=2, column=2, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Button(d, text="Inspect file...", command=self.on_inspect).grid(row=2, column=5, sticky="e", pady=(5, 0))
        o_ = ttk.Frame(f)
        o_.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Label(o_, text="Orientation: rotate").grid(row=0, column=0)
        add(ttk.Combobox(o_, textvariable=v["rot"], state="readonly", values=["0", "90", "180", "270"], width=4)).grid(row=0, column=1, padx=(4, 4))
        ttk.Label(o_, text="deg").grid(row=0, column=2)
        add(ttk.Checkbutton(o_, text="flip left-right", variable=v["flipx"])).grid(row=0, column=3, padx=(10, 0))
        add(ttk.Checkbutton(o_, text="flip up-down", variable=v["flipy"])).grid(row=0, column=4, padx=(10, 0))

        # -- what to plot ------------------------------------------------------------------------
        f = ttk.LabelFrame(left, text="Plot", padding=8)
        f.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Variable").grid(row=0, column=0, sticky="w")
        self.cb_var = add(ttk.Combobox(f, textvariable=v["variable"], state="readonly", width=40, values=[]))
        self.cb_var.grid(row=0, column=1, sticky="ew", padx=4)
        self.cb_var.bind("<<ComboboxSelected>>", lambda e: self._on_variable())
        self.desc = ttk.Label(f, text="", foreground="#555", wraplength=400, justify="left")
        self.desc.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 4))
        ttk.Label(f, text="Main title").grid(row=2, column=0, sticky="w")
        add(ttk.Entry(f, textvariable=v["title"])).grid(row=2, column=1, sticky="ew", padx=4, pady=1)
        ttk.Label(f, text="Variable plotted").grid(row=3, column=0, sticky="w")
        add(ttk.Entry(f, textvariable=v["label"])).grid(row=3, column=1, sticky="ew", padx=4, pady=1)

        # -- frames ------------------------------------------------------------------------------
        f = ttk.LabelFrame(left, text="Frames", padding=8)
        f.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        r = ttk.Frame(f)
        r.grid(row=0, column=0, sticky="w")
        ttk.Label(r, text="Start").grid(row=0, column=0)
        add(ttk.Entry(r, textvariable=v["start"], width=8)).grid(row=0, column=1, padx=(3, 10))
        ttk.Label(r, text="End").grid(row=0, column=2)
        add(ttk.Entry(r, textvariable=v["end"], width=8)).grid(row=0, column=3, padx=(3, 10))
        ttk.Label(r, text="Every Nth").grid(row=0, column=4)
        add(ttk.Entry(r, textvariable=v["every"], width=5)).grid(row=0, column=5, padx=(3, 0))
        r = ttk.Frame(f)
        r.grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(r, text="Acquired at").grid(row=0, column=0)
        self.acq_lbl = ttk.Label(r, text="-", width=16, relief="sunken", anchor="e", padding=(3, 0))
        self.acq_lbl.grid(row=0, column=1, padx=(3, 10))
        ttk.Label(r, text="Video frame rate").grid(row=0, column=2)
        add(ttk.Entry(r, textvariable=v["vfps"], width=6)).grid(row=0, column=3, padx=(3, 3))
        ttk.Label(r, text="frames/s").grid(row=0, column=4)
        r = ttk.Frame(f)
        r.grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Label(r, text="Average (rolling) frames").grid(row=0, column=0)
        add(ttk.Entry(r, textvariable=v["avg"], width=6)).grid(row=0, column=1, padx=(4, 10))
        add(ttk.Checkbutton(r, text="start with partial windows", variable=v["partial"])).grid(row=0, column=2)
        add(ttk.Checkbutton(f, text="time starts at 0 at the Start frame", variable=v["tzero"])).grid(row=3, column=0, sticky="w", pady=(3, 0))
        r = ttk.Frame(f)
        r.grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Label(r, text="Time from").grid(row=0, column=0)
        add(ttk.Combobox(r, textvariable=v["tsrc"], state="readonly", values=TIME_SOURCES, width=18)).grid(row=0, column=1, padx=(4, 8))
        ttk.Label(r, text="manual rate").grid(row=0, column=2)
        add(ttk.Entry(r, textvariable=v["mfps"], width=7)).grid(row=0, column=3, padx=(4, 3))
        ttk.Label(r, text="frames/s").grid(row=0, column=4)
        v["tsrc"].trace_add("write", lambda *a: self._on_tsrc())
        v["mfps"].trace_add("write", lambda *a: self._on_tsrc())
        v["unit"].trace_add("write", lambda *a: self._on_unit())
        self.sum_lbl = ttk.Label(f, text="", foreground="#555", wraplength=400, justify="left")
        self.sum_lbl.grid(row=5, column=0, sticky="w", pady=(4, 0))
        for k in ("start", "end", "every", "vfps", "avg", "partial"):
            v[k].trace_add("write", lambda *a: self._summary())
        for k in ("avg", "start", "end", "every", "vfps", "partial", "tzero", "smooth", "ref_on", "ref_frame", "zsi", "cmap",
                  "cmap_custom", "reverse", "clim_mode", "plo", "phi", "vmin", "vmax", "image_px", "title", "rot", "flipx", "flipy",
                  "tsrc", "mfps", "unit"):
            v[k].trace_add("write", lambda *a: self._update_name())

        # -- processing --------------------------------------------------------------------------
        f = ttk.LabelFrame(left, text="Processing", padding=8)
        f.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        r = ttk.Frame(f)
        r.grid(row=0, column=0, sticky="w")
        ttk.Label(r, text="Smooth (px, 0 = off)").grid(row=0, column=0)
        add(ttk.Entry(r, textvariable=v["smooth"], width=5)).grid(row=0, column=1, padx=(4, 14))
        ttk.Label(r, text="Z of silicon (MRayl)").grid(row=0, column=2)
        add(ttk.Entry(r, textvariable=v["zsi"], width=6)).grid(row=0, column=3, padx=(4, 6))
        ttk.Button(r, text="Z table", width=7, command=self.on_ztable).grid(row=0, column=4)
        r = ttk.Frame(f)
        r.grid(row=1, column=0, sticky="w", pady=(5, 0))
        add(ttk.Checkbutton(r, text="Show change vs frame #", variable=v["ref_on"], command=self._on_ref)).grid(row=0, column=0)
        e = add(ttk.Entry(r, textvariable=v["ref_frame"], width=8))
        e.grid(row=0, column=1, padx=(4, 0))
        v["ref_frame"].trace_add("write", lambda *a: self._on_ref(False))

        # -- display -----------------------------------------------------------------------------
        f = ttk.LabelFrame(left, text="Display", padding=8)
        f.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Colormap").grid(row=0, column=0, sticky="w")
        add(ttk.Combobox(f, textvariable=v["cmap"], state="readonly", values=[c[0] for c in CMAPS], width=18)).grid(row=0, column=1, sticky="w", padx=4)
        add(ttk.Checkbutton(f, text="reverse", variable=v["reverse"])).grid(row=0, column=2, sticky="w")
        ttk.Label(f, text="or enter one").grid(row=1, column=0, sticky="w", pady=(3, 0))
        add(ttk.Entry(f, textvariable=v["cmap_custom"], width=26)).grid(row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=(3, 0))
        ttk.Label(f, text="(matplotlib name, e.g. cividis, hot, coolwarm_r  -  or colours: black,cyan,white)", foreground="#555",
                  wraplength=400, justify="left").grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Contrast").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.cb_clim = add(ttk.Combobox(f, textvariable=v["clim_mode"], state="readonly", values=CLIM_MODES, width=34))
        self.cb_clim.grid(row=3, column=1, columnspan=2, sticky="w", padx=4, pady=(6, 0))
        self.cb_clim.bind("<<ComboboxSelected>>", lambda e: self._on_clim())
        r = ttk.Frame(f)
        r.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(r, text="Percentiles low").grid(row=0, column=0)
        self.e_plo = add(ttk.Entry(r, textvariable=v["plo"], width=5))
        self.e_plo.grid(row=0, column=1, padx=(3, 8))
        ttk.Label(r, text="high").grid(row=0, column=2)
        self.e_phi = add(ttk.Entry(r, textvariable=v["phi"], width=5))
        self.e_phi.grid(row=0, column=3, padx=(3, 12))
        ttk.Label(r, text="min").grid(row=0, column=4)
        self.e_vmin = add(ttk.Entry(r, textvariable=v["vmin"], width=8))
        self.e_vmin.grid(row=0, column=5, padx=(3, 8))
        ttk.Label(r, text="max").grid(row=0, column=6)
        self.e_vmax = add(ttk.Entry(r, textvariable=v["vmax"], width=8))
        self.e_vmax.grid(row=0, column=7, padx=(3, 0))
        r = ttk.Frame(f)
        r.grid(row=5, column=0, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Label(r, text="Image size (px)").grid(row=0, column=0)
        add(ttk.Entry(r, textvariable=v["image_px"], width=6)).grid(row=0, column=1, padx=(4, 0))

        # -- right: preview, output, log -------------------------------------------------------------
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        top = ttk.Frame(right)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Preview frame #").grid(row=0, column=0)
        add(ttk.Entry(top, textvariable=v["preview_frame"], width=8)).grid(row=0, column=1, padx=(4, 8))
        self.btn_prev = ttk.Button(top, text="Preview", command=self.on_preview)
        self.btn_prev.grid(row=0, column=2)
        self.prev_lbl = ttk.Label(top, text="", foreground="#555")
        self.prev_lbl.grid(row=0, column=3, padx=10)
        self.canvas = tk.Canvas(right, bg=bg, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
        self.canvas.bind("<Configure>", lambda e: self._show_preview())
        self.canvas_text = self.canvas.create_text(10, 10, anchor="nw", fill="#555555", font=("TkDefaultFont", 10),
                                                   text="Load a run, choose the settings, then click Preview.")

        f = ttk.LabelFrame(right, text="Output", padding=8)
        f.grid(row=2, column=0, sticky="ew")
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Folder").grid(row=0, column=0, sticky="w")
        add(ttk.Entry(f, textvariable=v["out_dir"])).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4)
        add(ttk.Button(f, text="Browse...", command=self.on_browse_out)).grid(row=0, column=4)
        ttk.Label(f, text="File name").grid(row=1, column=0, sticky="w", pady=(4, 0))
        add(ttk.Entry(f, textvariable=v["out_name"])).grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        ttk.Label(f, text="Format").grid(row=1, column=2, sticky="e", pady=(4, 0))
        add(ttk.Combobox(f, textvariable=v["fmt"], state="readonly", values=FORMATS, width=6)).grid(row=1, column=3, padx=4, pady=(4, 0))
        self.ff_lbl = ttk.Label(f, text="", foreground="#555")
        self.ff_lbl.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.btn_ff = ttk.Button(f, text="Install ffmpeg", command=self.on_install_ffmpeg)
        self.btn_ff.grid(row=2, column=3, columnspan=2, sticky="e", pady=(4, 0))

        r = ttk.Frame(right)
        r.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        r.columnconfigure(2, weight=1)
        self.btn_gen = ttk.Button(r, text="Generate", command=self.on_generate)
        self.btn_gen.grid(row=0, column=0)
        self.btn_cancel = ttk.Button(r, text="Cancel", command=self.cancel.set, state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=6)
        self.bar = ttk.Progressbar(r, maximum=1.0)
        self.bar.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        lf = ttk.LabelFrame(right, text="Log", padding=4)
        lf.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        lf.columnconfigure(0, weight=1)
        self.log_box = tk.Text(lf, height=9, wrap="word", state="disabled", font=("Consolas", 9) if os.name == "nt" else ("TkFixedFont", 9))
        sb = ttk.Scrollbar(lf, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        self.log_box.grid(row=0, column=0, sticky="ew")
        sb.grid(row=0, column=1, sticky="ns")

        v["fmt"].trace_add("write", lambda *a: self._refresh_ffmpeg())
        self._on_clim()

    # ---- small helpers ---------------------------------------------------------------------------------------
    def log(self, text):
        self.q.put(("log", text))

    def _log_now(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "log":
                    self._log_now(m[1])
                elif m[0] == "progress":
                    self.bar["value"] = m[1]
                elif m[0] == "preview":
                    self.preview_pil = m[1]
                    self.prev_lbl.config(text="")
                    self._show_preview()
                elif m[0] == "done":
                    self._set_busy(False)
                elif m[0] == "ffmpeg":
                    self._refresh_ffmpeg()
                elif m[0] == "run":
                    self._apply_run(m[1])
                elif m[0] == "error":
                    messagebox.showerror("Cannot load run", m[1])
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _set_busy(self, busy):
        self.busy = busy
        st = "disabled" if busy else "normal"
        for w in self.locked:
            try:
                w.configure(state="disabled" if busy else (w._normal_state if hasattr(w, "_normal_state") else "normal"))
            except tk.TclError:
                pass
        self.btn_prev.configure(state=st)
        self.btn_gen.configure(state=st)
        self.btn_ff.configure(state=st)
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        if not busy:
            self._on_clim()
            self._restore_combo_states()

    def _restore_combo_states(self):
        for w in self.locked:
            if isinstance(w, ttk.Combobox):
                w.configure(state="readonly")

    def _show_preview(self):
        c = self.canvas
        if self.preview_pil is None:
            return
        from PIL import Image, ImageTk
        cw, ch = max(10, c.winfo_width() - 4), max(10, c.winfo_height() - 4)
        im = self.preview_pil
        s = min(cw / im.width, ch / im.height, 1.0)
        if s < 1.0:
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(im)
        c.delete("all")
        c.create_image(cw // 2 + 2, ch // 2 + 2, image=self._photo, anchor="center")

    def _summary(self):
        try:
            o = self._read_numbers(strict=False)
        except Exception:
            return
        if self.run is None or o is None:
            self.sum_lbl.config(text="")
            return
        n = len(frame_list(self.run, o))
        if n <= 0:
            self.sum_lbl.config(text="No frames: the averaging window is longer than the selected range.")
            return
        speed = o.vfps * o.step / self.run.fps if self.run.fps == self.run.fps and self.run.fps > 0 else float("nan")
        self.sum_lbl.config(text=f"Video: {n} frames, {n / o.vfps:.1f} s long, plays at {speed:.2f} x real time.")

    def _read_numbers(self, strict=True):
        """Parse the frame fields.  Returns a namespace (without display fields) or None while the fields are incomplete."""
        v = self.v
        run = self.run
        if run is None:
            return None
        try:
            start, end = int(float(v["start"].get())), int(float(v["end"].get()))
            avg, step = int(float(v["avg"].get())), int(float(v["every"].get()))
            vfps = float(v["vfps"].get())
        except ValueError:
            if strict:
                raise ValueError("Start, End, Every Nth, Average and Video frame rate must be numbers.")
            return None
        if strict:
            if not (1 <= start < end <= run.n):
                raise ValueError(f"Start / End must satisfy 1 <= Start < End <= {run.n}.")
            if avg < 1 or avg > end - start + 1:
                raise ValueError(f"Average must be between 1 and {end - start + 1} (the number of frames in the selected range).")
            if step < 1:
                raise ValueError("Every Nth must be 1 or larger.")
            if not vfps > 0:
                raise ValueError("Video frame rate must be larger than 0.")
        elif not (1 <= start <= end <= run.n and avg >= 1 and step >= 1 and vfps > 0):
            return None
        return SimpleNamespace(start0=start - 1, end0=end - 1, avg=avg, step=step, vfps=vfps, partial=bool(v["partial"].get()))

    def read_opts(self):
        """Collect every setting into one object (main thread).  Raises ValueError with a readable message."""
        v = self.v
        if self.run is None:
            raise ValueError("Load a run first.")
        o = self._read_numbers(strict=True)
        name = v["variable"].get()
        if name not in self.var_names:
            raise ValueError("Choose a variable.")
        o.variable = self.var_names[name]
        try:
            o.smooth = float(v["smooth"].get())
            o.zsi = float(v["zsi"].get())
            o.plo, o.phi = float(v["plo"].get()), float(v["phi"].get())
            o.image_px = int(float(v["image_px"].get()))
        except ValueError:
            raise ValueError("Smooth, Z of silicon, percentiles and image size must be numbers.")
        if o.smooth < 0 or o.zsi <= 0:
            raise ValueError("Smooth must be >= 0 and Z of silicon > 0.")
        if not (0 <= o.plo < o.phi <= 100):
            raise ValueError("Percentiles must satisfy 0 <= low < high <= 100.")
        if not 120 <= o.image_px <= 4000:
            raise ValueError("Image size must be between 120 and 4000 px.")
        mode = v["clim_mode"].get()
        o.clim_mode = "global" if mode == CLIM_MODES[0] else ("frame" if mode == CLIM_MODES[1] else "manual")
        o.vmin = o.vmax = 0.0
        if o.clim_mode == "manual":
            try:
                o.vmin, o.vmax = float(v["vmin"].get()), float(v["vmax"].get())
            except ValueError:
                raise ValueError("Manual min / max must be numbers.")
            if not o.vmax > o.vmin:
                raise ValueError("Manual max must be larger than min.")
        o.ref_frame = None
        if v["ref_on"].get():
            try:
                rf = int(float(v["ref_frame"].get()))
            except ValueError:
                raise ValueError("The reference frame must be a number.")
            if not 1 <= rf <= self.run.n:
                raise ValueError(f"The reference frame must be between 1 and {self.run.n}.")
            o.ref_frame = rf - 1
        custom = v["cmap_custom"].get().strip()
        o.cmap_spec = custom if custom else CMAP[v["cmap"].get()]
        o.reverse = bool(v["reverse"].get())
        make_lut(o.cmap_spec, o.reverse)                         # validates the colormap now
        o.tzero = bool(v["tzero"].get())
        o.rot = int(v["rot"].get() or 0)
        o.flipx, o.flipy = bool(v["flipx"].get()), bool(v["flipy"].get())
        try:
            self.run.pitch_um = float(v["pitch"].get())
            if not self.run.pitch_um > 0:
                raise ValueError
        except ValueError:
            raise ValueError("Pixel pitch must be a number larger than 0.")
        try:
            self.run.freq_mhz = float(v["freq"].get()) if v["freq"].get().strip() else 0.0
        except ValueError:
            raise ValueError("Frequency must be a number (MHz).")
        if o.variable == "tof" and not self.run.freq_mhz > 0:
            raise ValueError("Enter the frequency (MHz) to use 'Phase shift as time'.")
        o.title, o.label = v["title"].get(), v["label"].get()
        o.fmt = v["fmt"].get()
        o.out_dir = v["out_dir"].get().strip() or os.path.join(self.run.folder, "video")
        o.out_name = v["out_name"].get().strip() or self._default_name(o)
        for ch in '<>:"/\\|?*':
            if ch in o.out_name:
                raise ValueError(f"The file name must not contain  {ch}")
        return o

    @staticmethod
    def _num(text, default=""):
        t = str(text).strip()
        try:
            return f"{float(t):g}"
        except ValueError:
            return t or default

    @staticmethod
    def _slug(text, n=30):
        out = "".join(c if (c.isalnum() or c in "._-+") else "-" for c in str(text).strip().replace(" ", "-"))
        while "--" in out:
            out = out.replace("--", "-")
        return out.strip("-")[:n]

    def _default_name(self, o=None):
        """File name built from every setting that changes the picture or the file, so a different setting = a different name."""
        v, run = self.v, self.run
        if run is None:
            return "video"
        key = self.var_names.get(v["variable"].get(), "var")
        parts = [run.name, key, "avg" + self._num(v["avg"].get(), "1")]
        try:
            st, en = int(float(v["start"].get())), int(float(v["end"].get()))
            if (st, en) != (1, run.n):
                parts.append(f"f{st}-{en}")
        except ValueError:
            pass
        if self._num(v["every"].get(), "1") != "1":
            parts.append("every" + self._num(v["every"].get()))
        if v["partial"].get():
            parts.append("partial")
        if v["rot"].get() not in ("0", ""):
            parts.append("rot" + v["rot"].get())
        if v["flipx"].get():
            parts.append("flipx")
        if v["flipy"].get():
            parts.append("flipy")
        if v["tsrc"].get() == TIME_SOURCES[1]:
            parts.append("tfit")
        elif v["tsrc"].get() == TIME_SOURCES[2]:
            parts.append("tman" + self._num(v["mfps"].get()))
        if v["tzero"].get():
            parts.append("t0")
        if self._num(v["smooth"].get(), "0") not in ("0", ""):
            parts.append("smooth" + self._num(v["smooth"].get()))
        if v["ref_on"].get():
            parts.append("ref" + self._num(v["ref_frame"].get()))
        if key in ("impedance", "impedance_iq") and self._num(v["zsi"].get()) != f"{Z_SI_MRAYL:g}":
            parts.append("zsi" + self._num(v["zsi"].get()))
        custom = v["cmap_custom"].get().strip()
        parts.append(self._slug(custom, 24) if custom else self._slug(v["cmap"].get(), 24).lower())
        if v["reverse"].get():
            parts.append("rev")
        mode = v["clim_mode"].get()
        if mode == CLIM_MODES[0]:
            parts.append(f"p{self._num(v['plo'].get())}-{self._num(v['phi'].get())}")
        elif mode == CLIM_MODES[1]:
            parts.append(f"perframe-p{self._num(v['plo'].get())}-{self._num(v['phi'].get())}")
        else:
            parts.append(f"lim{self._num(v['vmin'].get())}to{self._num(v['vmax'].get())}")
        if self._num(v["image_px"].get()) != "640":
            parts.append("px" + self._num(v["image_px"].get()))
        parts.append("fps" + self._num(v["vfps"].get()))
        title = v["title"].get().strip()
        if title and title != run.name:
            parts.append(self._slug(title, 24))
        name = "_".join(self._slug(p, 60) for p in parts if p)
        if len(name) > 150:                                      # keep names unique when they have to be shortened
            import zlib
            name = name[:140] + "_%05x" % (zlib.crc32(name.encode()) & 0xfffff)
        return name

    # ---- events ------------------------------------------------------------------------------------------------
    def on_browse(self):
        d = filedialog.askdirectory(title="Choose the run folder (timestamp folder)", initialdir=self.v["run_dir"].get() or None)
        if d:
            self.v["run_dir"].set(os.path.normpath(d))
            self.on_load()

    def on_browse_out(self):
        d = filedialog.askdirectory(title="Choose the output folder", initialdir=self.v["out_dir"].get() or None)
        if d:
            self.v["out_dir"].set(os.path.normpath(d))

    def _read_spec(self):
        v = self.v
        try:
            size = int(float(v["imgsize"].get()))
        except ValueError:
            raise ValueError("Image size must be a whole number of pixels (e.g. 128).")
        if size < 1:
            raise ValueError("Image size must be at least 1.")
        h = v["header"].get().strip().lower()
        header = None
        if h not in ("", "auto"):
            try:
                header = int(float(h))
            except ValueError:
                raise ValueError("Header bytes must be 'auto' or a number.")
            if header < 0:
                raise ValueError("Header bytes must be 0 or more.")
        return SimpleNamespace(name=v["dfmt"].get(), endian=v["endian"].get(), header=header, size=size)

    def on_load(self):
        path = self.v["run_dir"].get().strip().strip('"')
        if not path or self.busy:
            return
        self.v["run_dir"].set(path)
        try:
            spec = self._read_spec()
        except ValueError as e:
            self._log_now(f"Input error: {e}")
            return

        def job():
            try:
                run = Run2(path, spec, self.log, lambda f: self.q.put(("progress", f)), self.cancel)
            except Cancelled:
                raise
            except Exception as e:
                self.q.put(("error", str(e)))
                raise
            self.q.put(("run", run))
        self._start(job)

    def on_inspect(self):
        d = self.v["run_dir"].get().strip().strip('"')
        path = filedialog.askopenfilename(title="Choose a .dat file to inspect", initialdir=d if os.path.isdir(d) else None,
                                          filetypes=[("DAT files", "*.dat"), ("All files", "*.*")])
        if not path:
            return
        try:
            size = int(float(self.v["imgsize"].get()))
        except ValueError:
            size = 128
        try:
            for line in inspect_file(path, size):
                self._log_now(line)
        except Exception as e:
            self._log_now(f"ERROR: {e}")

    # menu texts carry the unit chosen in the window
    def _unit(self):
        return self.v["unit"].get().strip() or "a.u."

    def _u(self, text):
        return text.replace("(V)", f"({self._unit()})")

    def _rebuild_vars(self, select_key=None):
        run = self.run
        avail = run.available_vars() if run is not None else []
        self.var_names = {self._u(VAR[k][1]): k for k in avail}
        self.cb_var.configure(values=list(self.var_names))
        return avail

    def _on_unit(self):
        if self.run is None:
            return
        key = self.var_names.get(self.v["variable"].get())
        self._rebuild_vars()
        if key:
            for name, k in self.var_names.items():
                if k == key:
                    self.v["variable"].set(name)
            self._set_auto_label()

    def _on_tsrc(self):
        run = self.run
        if run is None:
            return
        try:
            mf = float(self.v["mfps"].get())
        except ValueError:
            mf = 0.0
        mode = self.v["tsrc"].get()
        if mode == TIME_SOURCES[2] and not mf > 0:
            return
        if run.stamp_bad and mode != TIME_SOURCES[2]:
            self._log_now("The file time stamps are not usable for this run - use 'Manual frame rate'.")
            self.v["tsrc"].set(TIME_SOURCES[2])
            return
        run.set_time_mode(mode, mf)
        self.acq_lbl.config(text=f"{run.fps:.3f} frames/s" if run.fps == run.fps else "n/a")
        self._summary()

    def _apply_run(self, run):
        self.run = run
        self.cache.clear()
        v = self.v
        avail = self._rebuild_vars()
        cur = v["variable"].get()
        if cur not in self.var_names:
            pref = self._u(self._pref_variable) if self._pref_variable else None
            v["variable"].set(pref if pref in self.var_names else
                              (self._u(VAR["reflection"][1]) if "reflection" in avail else self._u(VAR[avail[0]][1])))
        for k in (x[0] for x in VARS):
            if k not in avail:
                self._log_now(f"  not available: {VAR[k][1]}  ({run.unavailable_reason(k)})")
        v["start"].set("1")
        v["end"].set(str(run.n))
        v["preview_frame"].set(str(max(1, run.n // 2)))
        v["ref_frame"].set("1")
        try:
            if int(float(v["avg"].get())) > run.n:
                v["avg"].set("1")
        except ValueError:
            v["avg"].set("1")
        m = re.match(r"^\d{4}-\d{2}-\d{2}[ T_]\d{2}[-:]\d{2}[-:]\d{2}[_ -]*(.*)$", run.name)
        v["title"].set((m.group(1).replace("_", " ").strip() if m and m.group(1).strip() else run.name))
        new_out = os.path.join(run.folder, "video")
        if not v["out_dir"].get().strip() or v["out_dir"].get() == self._auto_out:
            v["out_dir"].set(new_out)
        self._auto_out = new_out
        if v["out_name"].get() == self._auto_name:
            v["out_name"].set("")
        self._auto_name = ""
        try:
            run.pitch_um = float(v["pitch"].get())
        except ValueError:
            pass
        if run.stamp_bad:
            v["tsrc"].set(TIME_SOURCES[2])
        elif v["tsrc"].get() != TIME_SOURCES[0]:
            self._on_tsrc()
        try:
            mf = float(v["mfps"].get())
        except ValueError:
            mf = 1.0
        run.set_time_mode(v["tsrc"].get(), mf if mf > 0 else 1.0)
        self._on_variable()
        self.acq_lbl.config(text=f"{run.fps:.3f} frames/s" if run.fps == run.fps else "n/a")
        bg = "yes" if run.bg else ("no  (" + run.bg_note + ")" if run.bg_note else "no")
        fx, fy = run.w * run.pitch_um / 1000.0, run.h * run.pitch_um / 1000.0
        self.info.config(text=f"{run.n} frames   {run.h} x {run.w} px   FOV {fx:.2f} x {fy:.2f} mm²\n"
                              f"{run.fmt.desc}\nAir baseline: {bg}")
        self._log_now(f"Loaded {run.folder}")
        self._log_now(f"  {run.n} paired frames (file numbers {run.frame_numbers[0]} - {run.frame_numbers[-1]}), {run.h} x {run.w} px, "
                      f"pixel pitch {run.pitch_um:g} um, air baseline: {bg}")
        self._log_now(f"  frame rate {run.fps:.3f} echo frames/s over {run.et[-1] - run.et[0]:.1f} s   ({run.stamp_note})")
        if run.note:
            self._log_now("  note: " + run.note.strip())
        self.preview_pil = None
        self.canvas.delete("all")
        self.canvas_text = self.canvas.create_text(10, 10, anchor="nw", fill="#555555", text="Choose the settings, then click Preview.")
        self._summary()

    def _on_variable(self):
        key = self.var_names.get(self.v["variable"].get())
        if not key:
            return
        self.desc.config(text=VAR[key][4])
        self._set_auto_label(force=True)
        self._update_name()
        self.cache.clear()

    def _update_name(self):
        if self.run is None:
            return
        new = self._default_name()
        cur = self.v["out_name"].get()
        if not cur or cur == self._auto_name:
            self.v["out_name"].set(new)
        self._auto_name = new

    def _set_auto_label(self, force=False):
        key = self.var_names.get(self.v["variable"].get())
        if not key:
            return
        new = self._u(VAR[key][2])
        if self.v["ref_on"].get():
            new += f", change vs frame {self.v['ref_frame'].get().strip() or '?'}"
        cur = self.v["label"].get()
        if force or cur == self._auto_label or not cur:
            self.v["label"].set(new)
        self._auto_label = new

    def _on_ref(self, user=True):
        self._set_auto_label()

    def _on_clim(self):
        mode = self.v["clim_mode"].get()
        manual = mode == CLIM_MODES[2]
        if self.busy:
            return
        for e in (self.e_plo, self.e_phi):
            e.configure(state="disabled" if manual else "normal")
        for e in (self.e_vmin, self.e_vmax):
            e.configure(state="normal" if manual else "disabled")

    def on_ztable(self):
        txt = "Approximate acoustic impedance Z (MRayl = 10^6 kg/m2/s):\n\n" + "\n".join(f"{n:<30}{z:>10}" for n, z in REFERENCE_Z)
        txt += ("\n\nThe impedance variables assume the baseline is air (Z ~ 0) and use\nr = (Z - Z_Si)/(Z + Z_Si) at the silicon / sample interface."
                "\nValues are typical, for orientation only.")
        messagebox.showinfo("Acoustic impedances", txt)

    # ---- ffmpeg ------------------------------------------------------------------------------------------------
    def _refresh_ffmpeg(self):
        exe = ffmpeg_exe()
        if exe:
            self.ff_lbl.config(text="ffmpeg found - mp4, avi and gif available.")
            self.btn_ff.grid_remove()
        else:
            self.ff_lbl.config(text="ffmpeg not found - only GIF possible (slower, larger).")
            self.btn_ff.grid()

    def on_install_ffmpeg(self):
        if self.busy:
            return
        self._set_busy(True)

        def work():
            self.log("Installing ffmpeg:  pip install imageio-ffmpeg   (a few seconds) ...")
            try:
                p = subprocess.Popen([sys.executable, "-m", "pip", "install", "imageio-ffmpeg"], stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, creationflags=0x08000000 if os.name == "nt" else 0)
                for line in p.stdout:
                    line = line.rstrip()
                    if line:
                        self.log("  " + line[:160])
                p.wait()
                importlib.invalidate_caches()
                if ffmpeg_exe():
                    self.log("ffmpeg is ready.")
                else:
                    self.log("ERROR: ffmpeg is still not available (pip returned " + str(p.returncode) + ").")
            except Exception as e:
                self.log(f"ERROR: {e}")
            self.q.put(("ffmpeg",))
            self.q.put(("done",))
        threading.Thread(target=work, daemon=True).start()

    # ---- jobs ------------------------------------------------------------------------------------------------
    def _start(self, fn):
        self.cancel.clear()
        self.bar["value"] = 0
        self._set_busy(True)

        def work():
            try:
                fn()
            except Cancelled:
                self.log("Cancelled.")
            except Exception as e:
                import traceback
                self.log(f"ERROR: {e}")
                self.log("  " + traceback.format_exc().strip().splitlines()[-2].strip())
            finally:
                self.q.put(("done",))
        threading.Thread(target=work, daemon=True).start()

    def on_preview(self):
        try:
            o = self.read_opts()
            k = int(float(self.v["preview_frame"].get())) - 1
            if not 0 <= k < self.run.n:
                raise ValueError(f"Preview frame must be between 1 and {self.run.n}.")
        except ValueError as e:
            self._log_now(f"Input error: {e}")
            return
        run = self.run

        def job():
            fr = preview_job(run, o, k, self.cache, self.log, self.cancel)
            self.q.put(("preview", fr))
        self._start(job)

    def on_generate(self):
        try:
            o = self.read_opts()
        except ValueError as e:
            self._log_now(f"Input error: {e}")
            return
        if o.fmt != "gif" and ffmpeg_exe() is None:
            self._log_now("ERROR: ffmpeg was not found - click 'Install ffmpeg' (or choose gif).")
            return
        path = os.path.join(o.out_dir, o.out_name + "." + o.fmt)
        if os.path.exists(path) and not messagebox.askyesno("File exists", f"{path}\nalready exists.  Overwrite?"):
            return
        self._save_prefs()
        run = self.run
        self._log_now(f"--- Generate: {self.v['variable'].get()}, average {o.avg}, frames {o.start0 + 1}-{o.end0 + 1} every {o.step}, {o.fmt} ---")

        def job():
            generate_job(run, o, self.cache, self.log, lambda f: self.q.put(("progress", f)), self.cancel)
            self.q.put(("progress", 1.0))
        self._start(job)

    # ---- preferences -------------------------------------------------------------------------------------------
    def _load_prefs(self):
        try:
            with open(PREFS_FILE) as f:
                d = json.load(f)
        except Exception:
            return
        for k in self.PREF_KEYS:
            if k in d and k in self.v and k not in ("variable",):
                try:
                    self.v[k].set(d[k])
                except Exception:
                    pass
        self._pref_variable = d.get("variable")
        self._on_clim()

    def _save_prefs(self):
        try:
            with open(PREFS_FILE, "w") as f:
                d = {k: self.v[k].get() for k in self.PREF_KEYS}
                d["variable"] = self.v["variable"].get()
                if d["out_dir"] == self._auto_out:                 # only remember an output folder the user chose
                    d["out_dir"] = ""
                json.dump(d, f, indent=1)
        except Exception:
            pass

    def on_close(self):
        self.cancel.set()
        self._save_prefs()
        self.root.destroy()


def main():
    if tk is None:
        print("tkinter is not available in this Python.")
        return
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
