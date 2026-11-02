# -*- coding: utf-8 -*-
"""
MEG2 sample-and-hold acquisition GUI   (v4)
===========================================

Run it (no arguments):      python meg2_snh_acquire.py

Needs next to this file (or in the "Driver folder" field):  fpga.py, j_fp_vco.py and xem7305.bit
Tick "Simulate (no hardware)" to try the window without the imager.

Time scale
----------
  Gate step 0 = the ADC samples at the moment TX closes, which is also when RX opens.  1 step = 5 ns, so step 1 is 5 ns
  after TX closes.  All times in the window and in the files are "after TX closes".
  The earliest gate is step 0, the latest step 160 (800 ns).  The default first echo is step 38 (190 ns after TX closes)
  for the 100 ns pulse.  Changing the pulse width moves TX close, RX open and everything that follows by the same amount.

Two tabs
--------
  Acquire                      the imager (everything below).
  Pulse and echo simulator     transmit pulse and the echoes from every interface of a layered chip (silicon die + up to 5
                               layers + top medium), with the sampling gate drawn on the same time axis.  No imager needed.

Modes
-----
  Live imaging            ONE frequency, ONE gate; frames as fast as the imager delivers (or every "frame interval").
  Sample & hold sweep     ONE frequency; the gate is stepped from start to end ONCE.
  Continuous sample & hold   the same sweep repeated until Stop (optional pause between sweeps).
  Frequency sweep         ONE gate; the VCO frequency is stepped from f1 to f2 (default 1800 ... 2000 MHz, 1 MHz).

Air reference (background)
--------------------------
  "Capture air" records echo AND no-echo frames without a sample.  What is recorded depends on the mode:
      live imaging         N frames at the live gate and frequency
      sample & hold        the whole gate range (default 1 frame per gate)
      frequency sweep      the whole frequency range at the gate
  The most recent air reference of each kind is kept and used for  sample - air  in the image and in the trace.
  A sweep cannot be started until an air reference for the same sweep exists; live imaging can (it shows raw).
  A copy of the air reference is written into every recording folder.

Timing of the acquisition
-------------------------
  Frame interval (s)      one frame (or one gate / frequency point) every x s; 0 = as fast as possible.
  Pause between sweeps    continuous sweeps: wait x s after every complete sweep.
  Burst / rest            acquire for x s, rest for y s, repeat (live imaging and continuous sweeps).  Each burst is a
                          set_01, set_02 ... sub folder.  Example: interval 0, burst 50, rest 3600, stop after 43200
                          -> 12 sets, one every hour.  RF and the imager are released during long rests.

Safety (Master settings button)
-------------------------------
  Delay after each gate / frequency change   waited after EVERY timing or VCO change before a frame is read.  The window refuses
                          values below MIN_DELAY_FLOOR_MS (below) - set that to what the hardware needs.
  Stop after (s)          every run ends by itself after this time (default 3600 s, 0 = no limit).
  Turn RF off when done   the VCO output is switched off when a run, Stop, a long rest or an error ends it.
  Limits                  DAC voltage, frequency, pulse width, gate range and every timing register are checked first.

Master settings (button)  also: 10 kHz frequency resolution, VCO output enable, no-echo shift, terminal count of sweeps, TX edge.

Display
-------
  Show                    I, Q or magnitude (raw, echo - air, echo - no-echo), phase, Reflection coefficient (vs silicon) and
                          Acoustic impedance (MRayl).  The last two use the no-echo frames when they exist, otherwise not.
  Plot settings           axes, title, description (f, gate step, frames averaged), font size.
  Trace                   the whole frame, a single pixel or a rectangular ROI (mean / max / ...) versus gate step or frequency.
  3D view                 the gate steps of one sweep stacked into a volume; start step = 0 um, depth = steps x 5 ns x c / 2.
                          XY, XZ and YZ views, click to move; "Napari" opens the stack in 3D (pip install "napari[all]").
  Generate video          (Recording) compiles images/png into video.mp4 (OpenCV, imageio-ffmpeg or the ffmpeg program).

Quick connection
----------------
  The DAC table (same value for every pixel) is loaded with ONE call when the driver has such a function (see FAST_DAC_METHOD
  below; it is also searched for automatically) instead of 32768 per-pixel writes.

What is written (one time-stamped folder per START; "Record" must be ticked)
-----------------------------------------------------------------------
  <save folder>/<YYYY-MM-DD HH-MM-SS>_<mode and range>[_<name>]/
      echo/echo_I_<n>_o.dat   echo/echo_Q_<n>_o.dat                       sample frames, float32 volts, 128 x 128 (meg2_video_gui.py)
      no-echo/noecho_I_<n>_o.dat   no-echo/noecho_Q_<n>_o.dat
      air-echo-I.dat air-echo-Q.dat air-noecho-I.dat air-noecho-Q.dat     live imaging: the air reference used
      air-sweep/echo, air-sweep/no-echo                                   sweeps: the air reference used, same file names
      images/png/frame_<n>.png     the picture as shown (rolling average, quantity, colormap, colour bar)
      images/tiff/frame_<n>.tif    the same image as 32-bit float numbers (volts) - open the folder as a stack in ImageJ
      images/*/integrated_steps_a-b   single sweeps: the image integrated over the chosen gate steps
      sweep.csv     one row per frame: phase, kind, index, set, pass, frequency, gate step, times, term count, time stamp
      settings.txt  all settings of the run
  With bursts every set_NN sub folder holds the folders above (so each set opens by itself in the video maker).
  The modification time of every file is the time the frame was acquired.
"""
import os
import sys
import json
import time
import queue
import inspect
import threading
import traceback
import collections

import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageFont, ImageTk

# ---------------------------------------------------------------------------------------------------------------------
# settings you may want to change (everything else is in the window)
# ---------------------------------------------------------------------------------------------------------------------
SIMULATE = False                                   # start with "Simulate (no hardware)" ticked
DRIVER_DIR = ""                                    # folder with fpga.py and j_fp_vco.py (empty = same folder as this script)
BIT_FILE = "xem7305.bit"
SAVE_ROOT = os.path.join(os.path.expanduser("~"), "MEG2_data")
PREFS_FILE = os.path.join(os.path.expanduser("~"), ".meg2_snh_acquire.json")

# ---- safety ---------------------------------------------------------------------------------------------------------
DEFAULT_DELAY_MS = 20.0                            # wait after every gate / frequency change - PLACEHOLDER, set from the hardware
MIN_DELAY_FLOOR_MS = 10.0                          # the window refuses anything smaller - PLACEHOLDER, set from the hardware
MAX_RUN_S_DEFAULT = 3600                           # every run ends by itself after this time (0 in the window = no limit)
RF_OFF_WHEN_DONE = True                            # default of the "Turn RF off when done" box
VCO_SETTLE_S = 0.1                                 # at least this long to wait after the VCO is (re)programmed at the start
RF_RELEASE_MIN_S = 5.0                             # rests this long or longer switch RF off and close the imager (if RF off is ticked)
DAC_V_MIN, DAC_V_MAX = 2.632, 2.9622               # the DAC code is 0 ... 511 in this range (convertVoltToDAC)
FREQ_MIN_MHZ, FREQ_MAX_MHZ = 35.0, 4400.0
PULSE_MIN_NS, PULSE_MAX_NS = 20, 200               # accepted transmit pulse widths

# ---- gate range and sweeps ------------------------------------------------------------------------------------------
STEP_MIN, STEP_MAX = 0, 160                        # gate steps after TX closes: 0 = RX opens, 160 = 800 ns
MAX_SWEEP_POINTS = 2500
FSWEEP_DEFAULT = ("1800", "2000", "1")             # frequency sweep from, to, step in MHz

# ---- fast DAC loading --------------------------------------------------------------------------------------------------
# Name of the driver function that writes ONE value to ALL pixels in a single call (called as fn(dac_code)).
# Leave "" to search xem for it automatically (a method with "dac" and all/same/every in its name that takes one argument).
FAST_DAC_METHOD = ""
FAST_DAC_ARG = "code"                              # what that function takes: "code" (0 ... 511, like LoadDACEntry) or "volts"

# ---- hardware numbers ---------------------------------------------------------------------------------------------
N = 128                                            # pixels per side
FRAME_BYTES = N * N * 2 * 2                        # 128 x 128 pixels x (I, Q) x uint16
NS_PER_STEP = 5                                    # one timing register step
TX_START_STEP = 20                                 # TX pulse starts at register step 20
PULSE_DEFAULT_NS = 100                             # default transmit pulse width
PULSE_EDGE_STEPS = 2                               # TX registers span this many steps more than the pulse width (20 ... 42 = 100 ns)
NOECHO_SHIFT = 90                                  # no-echo gate = echo gate + 90 steps
FIRST_ECHO_STEP = 38                               # default first echo: ADC at register step 80 = 38 steps after TX closes (42)
SHORT_TERM = False                                 # True: sweeps use the short terminal count of live imaging
AIR_FRAMES_LIVE, AIR_FRAMES_SWEEP = 5, 1           # default frames averaged for the air reference
Q_QUEUE_MAX = 200

MODE_LIVE, MODE_SNH, MODE_CONT, MODE_FREQ = "live", "snh", "cont", "freq"
MODE_LABELS = [("Live imaging  (1 gate, 1 frequency)", MODE_LIVE),
               ("Sample and hold sweep  (gate start to end, once)", MODE_SNH),
               ("Continuous sample and hold  (repeats the sweep)", MODE_CONT),
               ("Frequency sweep  (f1 to f2 at one gate)", MODE_FREQ)]
MODE_OF = dict(MODE_LABELS)
LABEL_OF = {v: k for k, v in MODE_LABELS}
MODE_NAME = {MODE_LIVE: "live", MODE_SNH: "snh-sweep", MODE_CONT: "snh-continuous", MODE_FREQ: "freq-sweep"}
BG_KIND = {MODE_LIVE: "live", MODE_SNH: "snh", MODE_CONT: "snh", MODE_FREQ: "freq"}
ADC_CHOICES = ["0 - gain of 5", "1 - no gain"]
PSET_CHOICES = ["0 - -4 dBm", "1 - -1 dBm", "2 - +2 dBm", "3 - +5 dBm"]
QUANTITIES = [
    ("Q  (echo - air)", "q_air"), ("I  (echo - air)", "i_air"), ("Magnitude  (echo - air)", "m_air"),
    ("Phase  (echo - air, deg)", "p_air"),
    ("Q  (echo - no-echo)", "q_ne"), ("I  (echo - no-echo)", "i_ne"), ("Magnitude of (echo - no-echo)", "m_ne"),
    ("Q  (echo, raw)", "q_raw"), ("I  (echo, raw)", "i_raw"), ("Magnitude  (echo, raw)", "m_raw")]
QUANTITIES += [("Reflection coefficient  (vs silicon)", "r_si"), ("Acoustic impedance  (MRayl)", "z_ac")]
QDICT = dict(QUANTITIES)
TRACE_QUANTITIES = [("Magnitude  (raw - air)", "m_air"), ("Magnitude  (raw)", "m_raw"), ("Same as the image shown", None)]
TQDICT = dict(TRACE_QUANTITIES)
CMAPS = ["inferno", "magma", "viridis", "plasma", "Spectral", "gray", "coolwarm", "seismic", "hot"]
SCALES = ["Auto (1-99 percentile)", "Fixed min / max"]
PLO, PHI = 1.0, 99.0
Z_SILICON_MRAYL = 19.64                            # acoustic impedance of silicon (the reference of the reflection coefficient)
Z_AIR_MRAYL = 0.0004
R_AIR_VS_SI = (Z_AIR_MRAYL - Z_SILICON_MRAYL) / (Z_AIR_MRAYL + Z_SILICON_MRAYL)   # = -0.99996: what the air reference reflects
C_SILICON_MS = 8433.0                              # speed of sound of silicon, for the depth axis of the 3D view
PIXEL_PITCH_UM = 50.0                              # default pixel pitch of the 3D view
VIDEO_FPS = 15                                     # playback rate of the video made from the PNG images
REGIONS = ["Whole frame", "Single pixel", "ROI"]
IMG_W, IMG_H = 760, 660                            # size of the PNG files
FONT_FILES = ["arial.ttf", "Arial.ttf", "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
              "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


class Cancelled(Exception):
    pass


def _state(w, on):
    if isinstance(w, ttk.Combobox):
        w.configure(state="readonly" if on else "disabled")
    else:
        w.configure(state="normal" if on else "disabled")


# ---------------------------------------------------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------------------------------------------------
def frange(a, b, step, digits):
    n = int(round((b - a) / step)) + 1
    return [round(a + k * step, digits) for k in range(n) if a + k * step <= b + 1e-9]


def tx_end_step(cfg):
    """Register step where TX closes (= where RX opens = gate step 0) for the pulse width of cfg."""
    return TX_START_STEP + int(round(cfg["width_ns"] / NS_PER_STEP)) + cfg["edge"]


def time_closed_ns(n):
    """ns after TX closes / RX opens of gate step n."""
    return n * NS_PER_STEP


def time_open_ns(cfg_or_width, n):
    """ns after TX opens (= the start of the pulse) of gate step n."""
    w = cfg_or_width["width_ns"] if isinstance(cfg_or_width, dict) else cfg_or_width
    return int(w) + n * NS_PER_STEP


def first_echo_ns(width_ns):
    """Where the default first echo lies, in ns after TX closes: a fixed time after TX opens (290 ns), so earlier for longer pulses."""
    return FIRST_ECHO_STEP * NS_PER_STEP + (PULSE_DEFAULT_NS - width_ns)


def pkey(f, n):
    return (round(float(f), 2), int(n))


def timing_for(cfg, n, kind):
    """Timing registers for gate step n (after TX closes) of kind 'echo' or 'noecho'; ValueError outside the register limits.
    The RX switch opens when TX closes.  Everything that follows moves with the pulse width."""
    E = tx_end_step(cfg)
    s = int(n) + (cfg["ne_shift"] if kind == "noecho" else 0)
    tx = (0, TX_START_STEP, E, TX_START_STEP, E)
    rx = (0, E, E + s + 2, E, E + s + 2)
    ge = (1, E + s - 9, 1023, E + s - 9, 1023)
    lo = (1, 1023, 1023, E, 1023)
    adc = (0, E + s, E + s + 1, E + s, E + s + 1)
    for nm, t in (("TX_SWITCH_EN", tx), ("RX_SWITCH_EN", rx), ("GLOB_EN", ge), ("ADC_CAPTURE", adc)):
        if min(t[1:]) < 0 or max(t[1:]) > 1023:
            raise ValueError(f"{nm} would leave 0 ... 1023 at gate step {n}{' (no-echo)' if kind == 'noecho' else ''} (values {t}). "
                             f"Reduce the gate range.")
    if cfg["mode"] == MODE_LIVE or cfg["short_term"]:           # fast: end the cycle just after the ADC capture
        tc = max(E + 41, max(adc[2], adc[4]) + 2)
    else:
        tc = 1023
    tc = int(min(max(tc, 1), 1023))
    if max(adc[2], adc[4]) >= tc and max(adc[2], adc[4]) < 1023:
        raise ValueError(f"terminal count {tc} ends before the ADC capture {adc} at gate step {n}")
    return dict(term=tc, tx=tx, pa=tx, rx=rx, ge=ge, lo=lo, adc=adc, shift=s)


def bytes_to_iq(buf):
    """Raw frame bytes -> I, Q in volts (float32, 128x128).  Same numbers as convertByteToADCVOLTS, ~100x faster."""
    a = np.frombuffer(bytes(buf), dtype="<u2")
    if a.size != N * N * 2:
        raise ValueError(f"frame has {a.size * 2} bytes, expected {FRAME_BYTES}")
    a = a.reshape(N, N, 2).astype(np.float32) * (1e-3 / 16.0)
    return np.ascontiguousarray(a[:, :, 0]), np.ascontiguousarray(a[:, :, 1])


def volts_to_raw(I, Q):
    a = np.stack([I, Q], axis=-1) * 16.0 / 1e-3
    return np.clip(np.round(a), 0, 65535).astype("<u2").tobytes()


class Roll:
    """Rolling mean of the last n frame sets (each a tuple of arrays or None); running sums in float64."""

    def __init__(self, n):
        self.n = max(1, int(n))
        self.win = collections.deque()
        self.sums = None
        self.pushes = 0

    def push(self, frames):
        if self.sums is None:
            self.sums = [None if f is None else np.zeros(f.shape, np.float64) for f in frames]
        for k, f in enumerate(frames):
            if f is not None:
                self.sums[k] += f
        self.win.append(frames)
        if len(self.win) > self.n:
            old = self.win.popleft()
            for k, f in enumerate(old):
                if f is not None:
                    self.sums[k] -= f
        self.pushes += 1
        if self.pushes % 500 == 0:                                       # remove accumulated rounding now and then
            self.sums = [None if f is None else sum(w[k].astype(np.float64) for w in self.win) for k, f in enumerate(self.win[0])]

    def mean(self):
        c = float(len(self.win))
        return [None if s is None else (s / c).astype(np.float32) for s in self.sums]

    def clear(self):
        self.win.clear()
        self.sums = None


def integrate_bundles(sel):
    """Mean of several raw frame bundles (echo, no-echo and the air reference at the same gates)."""
    def mean(key):
        arr = [x[key] for x in sel]
        return None if any(a is None for a in arr) else np.mean(arr, axis=0).astype(np.float32)
    def mean_ref(key):
        if all(x.get(key) is not None for x in sel):
            return (np.mean([x[key][0] for x in sel], axis=0).astype(np.float32),
                    np.mean([x[key][1] for x in sel], axis=0).astype(np.float32))
        return None
    return dict(i=mean("i"), q=mean("q"), ni=mean("ni"), nq=mean("nq"), ref_e=mean_ref("ref_e"), ref_n=mean_ref("ref_n"))


# ---------------------------------------------------------------------------------------------------------------------
# hardware back ends
# ---------------------------------------------------------------------------------------------------------------------
class RealBackend:
    """XEM7305 through fpga.py and j_fp_vco.py (the same calls as SNH_sweep_main.py)."""
    sim = False

    def __init__(self):
        self.xem = None
        self.jv = None
        self.dac_v = None
        self.vco_key = None
        self.key = None

    def connect(self, cfg, log, cancel):
        dd = cfg["driver_dir"] or os.path.dirname(os.path.abspath(__file__))
        for p in (dd, os.getcwd()):
            if p and p not in sys.path:
                sys.path.insert(0, p)
        try:
            import fpga
            import j_fp_vco
        except ImportError as e:
            raise RuntimeError(f"Cannot import the imager drivers ({e}). Put fpga.py and j_fp_vco.py next to this script or "
                               f"enter their folder in 'Driver folder'. (Tick 'Simulate' to test without hardware.)")
        self.jv = j_fp_vco
        bit = cfg["bit_file"]
        if not os.path.isabs(bit) and not os.path.exists(bit):
            for p in (dd, os.path.dirname(os.path.abspath(__file__))):
                if os.path.exists(os.path.join(p, bit)):
                    bit = os.path.join(p, bit)
                    break
        log("Opening the imager ...")
        xem = fpga.fpga()
        name = xem.BoardName()
        if name != "XEM7305":
            raise RuntimeError("Problem: board name = " + str(name) + "  (expected XEM7305)")
        try:
            log("Board: " + str(xem.di.deviceID) + " " + str(xem.di.serialNumber))
        except Exception:
            pass
        log("Loading bit file " + bit)
        xem.Configure(bit)
        try:
            log("Version: " + str(xem.Version()) + " serial number " + str(xem.SerialNumber()))
            log("Sys clock = %8.4f MHz" % xem.SysclkMHz())
        except Exception:
            pass
        self.xem = xem
        self.set_vco(cfg["points"][0][0], dict(cfg, outen=0), force=True)  # RF stays OFF until a run starts
        self.set_timing(timing_for(cfg, cfg["points"][0][1], "echo"))
        self.load_dac(cfg["dac"], log, cancel)
        xem.Close()
        time.sleep(0.05)
        self.key = (cfg["bit_file"], cfg["driver_dir"] or os.path.dirname(os.path.abspath(__file__)))

    # ---- DAC table: the same value for every pixel
    def _fast_dac_fn(self, log):
        x = self.xem
        if FAST_DAC_METHOD:
            fn = getattr(x, FAST_DAC_METHOD, None)
            if callable(fn):
                return FAST_DAC_METHOD, fn
            log(f"FAST_DAC_METHOD = '{FAST_DAC_METHOD}' does not exist in fpga.py - searching.")
        hits = []
        for name in dir(x):
            low = name.lower()
            if name.startswith("_") or "dac" not in low or "entry" in low:
                continue
            if not any(w in low for w in ("all", "same", "every", "global", "fill", "broadcast", "const")):
                continue
            fn = getattr(x, name, None)
            if not callable(fn):
                continue
            try:
                need = [p for p in inspect.signature(fn).parameters.values()
                        if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            except (TypeError, ValueError):
                continue
            if len(need) == 1:
                hits.append((0 if "all" in low else 1, name, fn))
        if hits:
            hits.sort(key=lambda h: (h[0], h[1]))
            return hits[0][1], hits[0][2]
        return None, None

    def load_dac(self, v, log, cancel):
        t0 = time.time()
        val = self.jv.convertVoltToDAC(v)
        name, fn = self._fast_dac_fn(log)
        if fn is not None:
            try:
                fn(float(v) if FAST_DAC_ARG == "volts" else val)
                self.dac_v = v
                log(f"DAC table loaded with ONE call ({name}): {v:.3f} V for all pixels (code {val}) in {time.time() - t0:.2f} s")
                return
            except Exception as e:
                log(f"Fast DAC load ({name}) failed: {e} - using the per-pixel loop instead.")
        else:
            names = [n for n in dir(self.xem) if "dac" in n.lower() and not n.startswith("_")]
            log("No fast 'same value for all pixels' DAC function found (set FAST_DAC_METHOD at the top of this file). "
                "DAC related functions in fpga.py: " + (", ".join(names) if names else "none"))
        log(f"Loading the DAC table pixel by pixel: {v:.3f} V for all pixels (code {val}) - this takes a while ...")
        for row in range(N):
            if cancel.is_set():
                raise Cancelled()
            for col in range(N):
                for iq in range(2):
                    self.xem.LoadDACEntry(row, col, iq, val)
            if row % 32 == 31:
                log(f"  DAC row {row + 1} of {N}")
        self.dac_v = v
        log(f"DAC table loaded in {time.time() - t0:.1f} s")

    def set_vco(self, f, cfg, force=False):
        key = (f, cfg["outen"], cfg["pset"], cfg["khz10"])
        if key == self.vco_key and not force:
            return False
        if cfg["khz10"]:
            self.jv.configureVCO_10khz(self.xem, f, cfg["outen"], cfg["pset"])
        else:
            self.jv.configureVCO(self.xem, f, cfg["outen"], cfg["pset"])
        self.vco_key = key
        return True

    def rf_off(self):
        """Switch the VCO output off (the imager must be open)."""
        if self.vco_key is None:
            return
        f, outen, pset, khz = self.vco_key
        if outen:
            self.set_vco(f, dict(outen=0, pset=pset, khz10=khz), force=True)

    def begin(self):
        self.xem.Open()

    def end(self):
        try:
            self.xem.Close()
        finally:
            time.sleep(0.02)

    def set_timing(self, t):
        self.jv.configTiming(self.xem, t["term"], t["tx"], t["pa"], t["rx"], t["ge"], t["lo"], t["adc"])

    def grab(self, adc):
        x = self.xem
        x.SelectADC(adc)                                       # 0 = gain of 5, 1 = no gain
        x.SelectFakeADC(0)
        x.EnablePgen(0)
        x.ResetFifo()
        x.EnablePipeTransfer(1)
        x.StartAcq()
        buf = bytearray(FRAME_BYTES)
        x.GetPipeData(buf)
        return buf

    def hint(self, **kw):
        pass

    def disconnect(self):
        try:
            if self.xem is not None:
                self.xem.Close()
        except Exception:
            pass
        self.xem = None


class SimBackend:
    """Synthetic imager: an echo that peaks at gate step ~63 (315 ns), a sample that changes the reflection, noise."""
    sim = True

    def __init__(self, speed=1.0):
        self.speed = speed
        self.dac_v = None
        self.vco_key = None
        self.key = None
        self.f = 1853.0
        self.t = None
        self.sample = True
        self.rng = np.random.default_rng(1)
        self.changed_at = None                                 # for the tests: time of the last timing change
        self.gaps = []                                         # seconds between a timing change and the next frame
        self.rf = 0
        self.rf_log = []
        yy, xx = np.mgrid[0:N, 0:N]
        self.ring = np.sin(np.hypot(xx - N * 0.4, yy - N * 0.55) / 4.0)
        self.leak_i = 0.40 + 0.05 * np.sin(xx / 17.0)
        self.leak_q = 0.30 + 0.05 * np.cos(yy / 23.0)

    def connect(self, cfg, log, cancel):
        log("Simulated imager ready (no hardware is used).")
        self.dac_v = cfg["dac"]
        self.key = ("sim",)

    def load_dac(self, v, log, cancel):
        log(f"(simulated) DAC {v:.3f} V")
        self.dac_v = v

    def set_vco(self, f, cfg, force=False):
        key = (f, cfg["outen"], cfg["pset"], cfg["khz10"])
        if key == self.vco_key and not force:
            return False
        self.vco_key = key
        self.f = f
        self.rf = cfg["outen"]
        self.rf_log.append(("vco", f, cfg["outen"]))
        self.changed_at = time.time()
        return True

    def rf_off(self):
        if self.vco_key is not None and self.vco_key[1]:
            self.set_vco(self.vco_key[0], dict(outen=0, pset=self.vco_key[2], khz10=self.vco_key[3]), force=True)

    def begin(self):
        pass

    def end(self):
        pass

    def set_timing(self, t):
        self.t = t
        self.changed_at = time.time()

    def hint(self, sample=None, **kw):
        if sample is not None:
            self.sample = sample

    def grab(self, adc):
        if self.changed_at is not None:
            self.gaps.append(time.time() - self.changed_at)
            self.changed_at = None
        t = self.t
        time.sleep((0.004 + 16384 * t["term"] * 5e-9 * 1.5) * self.speed)
        g = t["adc"][1] - t["tx"][2]                           # gate step after TX closes (no-echo: + shift)
        env = np.exp(-((g - 63.0) / 12.0) ** 2) * (1 + 0.3 * np.cos((self.f - 1853.0) / 60.0))
        refl = (0.55 + 0.35 * self.ring) if self.sample else 1.0
        sig = env * refl
        gain = 1.0 if adc == 1 else 5.0 / 5.0
        i = self.leak_i + sig * 0.6 + 0.004 * self.rng.normal(size=(N, N))
        q = self.leak_q + sig * 0.3 * gain + 0.004 * self.rng.normal(size=(N, N))
        return bytearray(volts_to_raw(i, q))

    def disconnect(self):
        pass


# ---------------------------------------------------------------------------------------------------------------------
# display
# ---------------------------------------------------------------------------------------------------------------------
_fonts = {}


def font(size):
    if size in _fonts:
        return _fonts[size]
    f = None
    for fn in FONT_FILES:
        try:
            f = ImageFont.truetype(fn, size)
            break
        except Exception:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except Exception:
            f = ImageFont.load_default()
    _fonts[size] = f
    return f


_luts = {}


def lut(name):
    if name not in _luts:
        try:
            from matplotlib import colormaps
            cm = colormaps[name]
            a = (np.array([cm(x / 255.0)[:3] for x in range(256)]) * 255).astype(np.uint8)
        except Exception:
            a = np.stack([np.arange(256)] * 3, axis=1).astype(np.uint8)
        _luts[name] = a
    return _luts[name]


def fmt(v):
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1000 or a < 0.01:
        return f"{v:.2e}"
    return f"{v:.3g}" if a >= 100 else (f"{v:.4g}")


def orient(img, rot, fx, fy):
    k = (rot // 90) % 4
    if k:
        img = np.rot90(img, k)
    if fx:
        img = np.fliplr(img)
    if fy:
        img = np.flipud(img)
    return img


def reflection_image(b, key):
    """Reflection coefficient (relative to silicon) or acoustic impedance per pixel.  The air reference reflects with R = -1 (silicon to
    air), so  R = R_air * Re[(echo - no-echo) / (air echo - air no-echo)].  Without no-echo frames the raw echoes are divided."""
    ref = b.get("ref_e")
    if ref is None:
        img = np.hypot(b["i"].astype(np.float64), b["q"].astype(np.float64))
        return img, "V", "no air reference - magnitude shown"
    E = b["i"].astype(np.float64) + 1j * b["q"].astype(np.float64)
    Ea = ref[0].astype(np.float64) + 1j * ref[1].astype(np.float64)
    note = ""
    ne, na = b.get("ni"), b.get("ref_n")
    if ne is not None and na is not None:
        E = E - (ne.astype(np.float64) + 1j * b["nq"].astype(np.float64))
        Ea = Ea - (na[0].astype(np.float64) + 1j * na[1].astype(np.float64))
    else:
        note = "no-echo not used"
    Ea = np.where(np.abs(Ea) < 1e-12, 1e-12, Ea)
    R = np.clip(R_AIR_VS_SI * (E / Ea).real, -0.9999, 0.9999)
    if key == "r_si":
        return R, "", note
    return Z_SILICON_MRAYL * (1.0 + R) / (1.0 - R), "", note                  # the name already says MRayl


def quantity_image(b, key):
    """Returns (image, unit, note)."""
    if key in ("r_si", "z_ac"):
        return reflection_image(b, key)
    I, Q = b["i"].astype(np.float64), b["q"].astype(np.float64)
    ref = b.get("ref_e")
    note = ""
    if key.endswith("_air"):
        if ref is None:
            note = "no air reference yet - raw"
            key = key.replace("_air", "_raw")
        else:
            Ra, Rq = ref[0].astype(np.float64), ref[1].astype(np.float64)
            if key == "q_air":
                return Q - Rq, "V", note
            if key == "i_air":
                return I - Ra, "V", note
            if key == "m_air":
                return np.hypot(I, Q) - np.hypot(Ra, Rq), "V", note
            d = np.degrees(np.arctan2(Q, I) - np.arctan2(Rq, Ra))
            return (d + 180.0) % 360.0 - 180.0, "deg", note
    if key.endswith("_ne"):
        if b.get("ni") is None:
            note = "no-echo is off - raw"
            key = key.replace("_ne", "_raw")
        else:
            dI, dQ = I - b["ni"].astype(np.float64), Q - b["nq"].astype(np.float64)
            return {"q_ne": dQ, "i_ne": dI, "m_ne": np.hypot(dI, dQ)}[key], "V", note
    if key == "q_raw":
        return Q, "V", note
    if key == "i_raw":
        return I, "V", note
    return np.hypot(I, Q), "V", note


def vtext(img, xy, text, fnt, fill):
    """Text turned by 90 degrees, centred at xy."""
    box = fnt.getbbox(text)
    tw, th = box[2] - box[0] + 6, box[3] - box[1] + 6
    tmp = Image.new("RGBA", (tw, th), (255, 255, 255, 0))
    ImageDraw.Draw(tmp).text((3 - box[0], 3 - box[1]), text, fill=fill, font=fnt)
    tmp = tmp.rotate(90, expand=True)
    img.paste(tmp, (int(xy[0] - tmp.width / 2), int(xy[1] - tmp.height / 2)), tmp)


def wrap_text(dr, text, fnt, width):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if cur and dr.textlength(t, font=fnt) > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def img_opts(disp):
    return dict(axes=bool(disp.get("axes", True)), title=bool(disp.get("title", True)), desc=bool(disp.get("desc", True)),
                fs=int(disp.get("fs", 14)))


def render_image(img, vmin, vmax, cmap, W, H, title, sub, rot, fx, fy, opts=None):
    """The 2D map.  opts: axes (pixel rows and columns with labels), title, desc (the line under the map), fs (font size),
    roi (r0, r1, c0, c1 in displayed pixels, drawn on the map)."""
    o = dict(axes=True, title=True, desc=True, fs=14, roi=None)
    o.update(opts or {})
    fs = max(8, min(40, int(o["fs"])))
    W, H = max(W, 200), max(H, 200)
    out = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(out)
    top = 8
    if o["title"]:
        dr.text((10, 6), title, fill="black", font=font(fs + 6))
        top = 6 + (fs + 6) + 16
    ax_h = int(fs * 2.8) if o["axes"] else 6
    lines = wrap_text(dr, sub, font(fs), W - 20) if (o["desc"] and sub) else []
    desc_h = len(lines) * (fs + 6) + 8 if lines else 0
    lm = int(fs * 3.6) if o["axes"] else 8
    cb_w = 30
    right = cb_w + 16 + int(fs * 6.2)
    side = max(min(W - lm - right, H - top - ax_h - desc_h - 4), 64)
    n = 128
    if img is not None:
        im = orient(img, rot, fx, fy)
        n = im.shape[0]
        rng = (vmax - vmin) if vmax > vmin else 1.0
        idx = (np.clip((im - vmin) / rng, 0, 1) * 255).astype(np.uint8)
        rgb = lut(cmap)[idx]
        out.paste(Image.fromarray(rgb).resize((side, side), Image.NEAREST), (lm, top))
    dr.rectangle([lm, top, lm + side - 1, top + side - 1], outline="#999999")
    if o["axes"]:
        for k in sorted({0, n // 4, n // 2, 3 * n // 4, n - 1}):
            x = lm + (k + 0.5) / n * side
            y = top + (k + 0.5) / n * side
            dr.line([x, top + side, x, top + side + 5], fill="#444444")
            dr.text((x, top + side + 7), str(k), fill="black", font=font(fs), anchor="mt")
            dr.line([lm - 5, y, lm, y], fill="#444444")
            dr.text((lm - 8, y), str(k), fill="black", font=font(fs), anchor="rm")
        dr.text((lm + side / 2, top + side + 8 + fs + 4), "column", fill="#333333", font=font(fs), anchor="mt")
        vtext(out, (fs * 0.9, top + side / 2), "row", font(fs), "#333333")
    roi = o.get("roi")
    if roi and img is not None:
        r0, r1, c0, c1 = roi
        xa, ya = lm + c0 / n * side, top + r0 / n * side
        dr.rectangle([xa, ya, max(lm + (c1 + 1) / n * side - 1, xa + 2), max(top + (r1 + 1) / n * side - 1, ya + 2)],
                     outline="#00e5ff", width=2)
    cx = lm + side + 16
    grad = lut(cmap)[np.linspace(255, 0, side).astype(int)]
    out.paste(Image.fromarray(np.repeat(grad[:, None, :], cb_w, axis=1).astype(np.uint8)), (cx, top))
    dr.rectangle([cx, top, cx + cb_w - 1, top + side - 1], outline="#999999")
    for k in range(5):
        y = top + int(k * (side - 1) / 4)
        v = vmax - k * (vmax - vmin) / 4
        dr.line([cx + cb_w, y, cx + cb_w + 5, y], fill="#444444")
        dr.text((cx + cb_w + 8, y), fmt(v), fill="black", font=font(fs), anchor="lm")
    y = top + side + ax_h + 4
    for ln in lines:
        dr.text((10, y), ln, fill="#333333", font=font(fs))
        y += fs + 6
    return out
def render_trace(xs, ys, W, H, xlabel, ylabel, prev=None, xr=None, marks=(), cur=None, peak=None):
    """Curve of the current pass (red), the previous pass (grey), a marker at the newest point, the default first-echo
    position and the strongest feature."""
    W, H = max(W, 200), max(H, 80)
    out = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(out)
    l, r, t, b = 62, W - 12, 8, H - 30
    dr.rectangle([l, t, r, b], outline="#999999")
    allx = list(xs) + (list(prev[0]) if prev else [])
    ally = list(ys) + (list(prev[1]) if prev else [])
    if len(allx) >= 2:
        x0, x1 = (xr if xr else (min(allx), max(allx)))
        y0, y1 = min(ally), max(ally)
        if x1 == x0:
            x1 = x0 + 1
        if y1 == y0:
            y1 = y0 + 1e-9
        pad = 0.08 * (y1 - y0)
        y0, y1 = y0 - pad, y1 + pad

        def P(x, y):
            return (l + (x - x0) / (x1 - x0) * (r - l), b - (y - y0) / (y1 - y0) * (b - t))
        for mx, ml in marks:
            if x0 <= mx <= x1:
                px = P(mx, y0)[0]
                for yy in range(t, b, 6):
                    dr.line([px, yy, px, min(yy + 3, b)], fill="#2e7d32")
                dr.text((px + 3, t + 1), ml, fill="#2e7d32", font=font(11), anchor="lt")
        if prev and len(prev[0]) >= 2:
            dr.line([P(x, y) for x, y in zip(*prev)], fill="#c8c8c8", width=2)
        if len(xs) >= 2:
            dr.line([P(x, y) for x, y in zip(xs, ys)], fill="#c0392b", width=2)
        if cur is not None and len(xs):
            px, py = P(cur, ys[-1])
            dr.ellipse([px - 4, py - 4, px + 4, py + 4], outline="#c0392b", fill="white", width=2)
        if peak is not None:
            px, py = P(peak[0], peak[1])
            dr.ellipse([px - 5, py - 5, px + 5, py + 5], outline="#1f4fd8", width=2)
            dr.text((r - 6, t + 14), peak[2], fill="#1f4fd8", font=font(12), anchor="rt")
        dr.text((l - 4, t), fmt(y1), fill="black", font=font(11), anchor="rt")
        dr.text((l - 4, b), fmt(y0), fill="black", font=font(11), anchor="rb")
        dr.text((l, b + 4), fmt(x0), fill="black", font=font(11), anchor="lt")
        dr.text((r, b + 4), fmt(x1), fill="black", font=font(11), anchor="rt")
    dr.text(((l + r) // 2, b + 4), xlabel, fill="#444444", font=font(11), anchor="mt")
    dr.text((4, (t + b) // 2), ylabel, fill="#444444", font=font(11), anchor="lm")
    return out

# ---------------------------------------------------------------------------------------------------------------------
# pulse and echo simulator: physics (no Tk in this part)
# ---------------------------------------------------------------------------------------------------------------------
# Plane-wave, normal-incidence model of a transducer on the BACK of a silicon die, looking up through a stack of layers.
#   pressure reflection at an interface (medium 1 -> medium 2):  R = (Z2 - Z1) / (Z2 + Z1),  transmission  T = 1 + R
#   echo from interface k (primary):  arrives after  2 * sum(thickness_j / c_j)  (j below the interface)
#   amplitude = transmit amplitude * product of (1 - R_j^2) of the interfaces it crossed twice * R_k * attenuation
# The pulse is a trapezoid envelope (rise and fall = "ramp", both inside the pulse width) on a carrier. Every echo is a
# complex phasor, so echoes that overlap (for example from a very thin layer) add with the correct phase.
ECHO_STEP_NS = 5.0                                  # one gate step = 5 ns
ECHO_MAX_STEP = 160                                 # 800 ns, the same limit as the acquisition tab
ECHO_MAX_LAYERS = 5                                 # layers above the silicon (the top medium comes in addition)
ECHO_DT_NS = 0.25                                   # time grid of the envelope curves
ECHO_MAX_EVENTS = 60000                             # stop enumerating reflections after this many (keeps the tab fast)
ECHO_ORDER_CAP = 8                                  # reflections counted separately up to this order
ECHO_BASE_THICK_UM = 635.0                          # silicon die
ECHO_SUPPORT_FRAC = 0.05                            # "echo present in a gate" = envelope above 5 % of its own peak
ECHO_FLAT_FRAC = 0.90                               # "flat top" = envelope above 90 % of its own peak
# series colours (reference categorical palette, adjacent order validated): interface 1 ... 6
ECHO_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]

# name, Z (MRayl), longitudinal speed of sound (m/s), attenuation at 1 GHz (dB/mm, scales with f^2, 0 = not set).
# Z and c are textbook room-temperature values (rounded); thin films can differ from bulk - edit them in the table.
ECHO_MATERIALS = [
    ("Silicon", 19.64, 8433.0, 0.2),
    ("Water", 1.48, 1480.0, 220.0),
    ("Gold", 62.6, 3240.0, 0.0),
    ("Air", 0.0004, 343.0, 0.0),
    ("Fat", 1.38, 1450.0, 100.0),
    ("Muscle", 1.70, 1580.0, 200.0),
    ("Skin", 1.99, 1730.0, 200.0),
    ("Blood", 1.66, 1575.0, 220.0),
    ("Liver", 1.65, 1570.0, 200.0),
    ("Bone (cortical)", 7.8, 4080.0, 0.0),
    ("Silicon dioxide", 13.1, 5970.0, 0.0),
    ("Silicon nitride", 32.0, 10300.0, 0.0),
    ("Glass (borosilicate)", 12.6, 5640.0, 0.0),
    ("Aluminum", 17.3, 6420.0, 0.0),
    ("Copper", 42.5, 4760.0, 0.0),
    ("Titanium", 27.3, 6070.0, 0.0),
    ("Platinum", 69.9, 3260.0, 0.0),
    ("Tungsten", 100.5, 5220.0, 0.0),
    ("Aluminum nitride", 36.0, 11000.0, 0.0),
    ("Zinc oxide", 36.0, 6370.0, 0.0),
    ("PDMS", 1.0, 1030.0, 0.0),
    ("Epoxy", 3.05, 2650.0, 0.0),
    ("Polyimide", 3.4, 2400.0, 0.0),
]
ECHO_CUSTOM = "Custom"
ECHO_UNITS = {"nm": 1e-9, "um": 1e-6, "mm": 1e-3}

# examples: base silicon thickness (um); layers (material, name, thickness, unit); top material
ECHO_EXAMPLES = [
    ("Water / Si / gold / Si / air", 635.0,
     [("Water", "Water", 20.0, "nm"), ("Silicon", "Silicon", 100.0, "um"), ("Gold", "Gold", 3.0, "um"), ("Silicon", "Silicon", 600.0, "um")], "Air"),
    ("Bare die in air", 635.0, [], "Air"),
    ("Die + water", 635.0, [("Water", "Water", 500.0, "um")], "Air"),
    ("Die + fat + muscle", 635.0, [("Fat", "Fat", 300.0, "um"), ("Muscle", "Muscle", 1000.0, "um")], "Air"),
    ("Die + skin + fat + muscle", 635.0,
     [("Skin", "Skin", 150.0, "um"), ("Fat", "Fat", 300.0, "um"), ("Muscle", "Muscle", 1000.0, "um")], "Air"),
    ("Two bonded dies (oxide bond)", 635.0,
     [("Silicon dioxide", "Oxide", 2.0, "um"), ("Silicon", "Silicon", 300.0, "um")], "Air"),
]


def echo_material(name):
    for m in ECHO_MATERIALS:
        if m[0] == name:
            return m
    return None


def pulse_env(t, t0, width, ramp):
    """Trapezoid envelope: starts at t0, rises over `ramp`, flat, falls over `ramp`, ends at t0 + width."""
    x = np.asarray(t, dtype=float) - t0
    r = min(max(ramp, 0.0), width / 2.0)
    if r <= 0:
        return ((x >= 0) & (x <= width)).astype(float)
    return np.clip(np.minimum(x / r, (width - x) / r), 0.0, 1.0)


def echo_events(stack, top_z, f_hz, use_att, multi, rb, amin, tmax_ns, max_events=ECHO_MAX_EVENTS):
    """Follow the wave through the stack. stack[0] is the silicon die (the transducer is at its bottom), stack[1:] the layers,
    each a dict(z, c, thick [m], alpha [dB/mm at 1 GHz]); top_z is the impedance of the (infinitely thick) top medium.
    Returns ([(arrival ns, complex amplitude, interface k, order)], truncated)."""
    import heapq
    import cmath
    n = len(stack) - 1
    Z = [s["z"] for s in stack] + [top_z]
    w = 2 * np.pi * f_hz
    tau = [s["thick"] / s["c"] * 1e9 for s in stack]                   # ns
    fac = []
    for s, ta in zip(stack, tau):
        a = 1.0
        if use_att and s.get("alpha", 0) > 0:
            a = 10 ** (-(s["alpha"] * (f_hz / 1e9) ** 2) * (s["thick"] * 1e3) / 20.0)
        fac.append(a * cmath.exp(-1j * w * ta * 1e-9))
    heap, pend, received = [], {}, []
    truncated = False

    def push(t, m, d, kmax, order, a):
        if abs(a) < amin or t > tmax_ns:
            return
        key = (m, d, kmax, min(order, ECHO_ORDER_CAP), int(round(t * 500)))
        p = pend.get(key)
        if p is None:
            pend[key] = [t, a]
            heapq.heappush(heap, (t, key))
        else:
            p[1] += a

    push(0.0, 0, 1, 0, 0, 1 + 0j)
    count = 0
    while heap:
        _t, key = heapq.heappop(heap)
        t, a = pend.pop(key)
        m, d, kmax, order, _ = key
        count += 1
        if count > max_events:
            truncated = True
            break
        t += tau[m]
        a *= fac[m]
        if d == 1:                                                     # going up, reaches interface m + 1
            k = m + 1
            R = (Z[k] - Z[m]) / (Z[k] + Z[m])
            push(t, m, -1, max(kmax, k), order + 1, a * R)
            if k <= n:
                push(t, k, 1, kmax, order, a * (1 + R))
        else:                                                          # going down, reaches interface m
            if m == 0:
                received.append((t, a, kmax, order))
                if multi and rb:
                    push(t, 0, 1, kmax, order, a * rb)
            else:
                Rd = (Z[m - 1] - Z[m]) / (Z[m - 1] + Z[m])
                push(t, m - 1, -1, kmax, order, a * (1 + Rd))
                if multi:
                    push(t, m, 1, kmax, order + 1, a * Rd)
    return received, truncated


def _conv(imp, kernel):
    return np.convolve(imp, kernel)[:len(imp)]


def curve_from_events(events, tgrid, dt, width, ramp, delay):
    """Complex envelope (relative to a transmit amplitude of 1) of a set of events on the grid tgrid."""
    imp = np.zeros(len(tgrid), dtype=complex)
    for t, a, _k, _o in events:
        x = (t + delay) / dt
        i = int(np.floor(x))
        fr = x - i
        if 0 <= i < len(imp):
            imp[i] += a * (1 - fr)
        if 0 <= i + 1 < len(imp):
            imp[i + 1] += a * fr
    kern = pulse_env(np.arange(0, width + ramp + 2 * dt, dt), 0.0, width, ramp)
    return _conv(imp, kern)


def ranges_text(steps):
    """[3,4,5,9] -> '3-5, 9'"""
    steps = sorted(set(steps))
    if not steps:
        return "-"
    out, a, b = [], steps[0], steps[0]
    for s in steps[1:]:
        if s == b + 1:
            b = s
        else:
            out.append((a, b))
            a = b = s
    out.append((a, b))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def echo_simulate(stack, top, pulse, opts, xmax_ns=1000.0, rf=False, rf_window=None):
    """stack: list of dict(name, z, c, thick, alpha) with stack[0] = the silicon die; top: dict(name, z);
    pulse: dict(f_ghz, amp, width, ramp, delay); opts: dict(att, multi, rb, amin_pct, gates=[dict(idx, a, b)]).
    Returns a dict with the interfaces, the complex curves, the table rows and the gate report."""
    f_hz = pulse["f_ghz"] * 1e9
    A, width, ramp, delay = pulse["amp"], pulse["width"], pulse["ramp"], pulse["delay"]
    n = len(stack) - 1
    tcalc = max(xmax_ns, width + ECHO_STEP_NS * (ECHO_MAX_STEP + 2)) + width + 20
    dt = ECHO_DT_NS
    tgrid = np.arange(0, tcalc, dt)
    ev, trunc = echo_events(stack, top["z"], f_hz, opts["att"], opts["multi"], opts["rb"], opts["amin_pct"] / 100.0, tcalc - delay)
    names = [s["name"] for s in stack] + [top["name"]]
    Z = [s["z"] for s in stack] + [top["z"]]
    ifaces, t_acc = [], 0.0
    for k in range(1, n + 2):
        t_acc += 2.0 * stack[k - 1]["thick"] / stack[k - 1]["c"] * 1e9
        R = (Z[k] - Z[k - 1]) / (Z[k] + Z[k - 1])
        ifaces.append(dict(k=k, label=f"{k}: {names[k - 1]} / {names[k]}", short=f"{names[k - 1]}/{names[k]}", R=R,
                           z1=Z[k - 1], z2=Z[k], rt=t_acc, color=ECHO_COLORS[(k - 1) % len(ECHO_COLORS)]))
    # curves: transmit, per interface (first echo, repeats), total
    tx = curve_from_events([(0.0, 1 + 0j, 0, 0)], tgrid, dt, width, ramp, 0.0)
    curves = {"tx": tx}
    for k in range(1, n + 2):
        prim = [e for e in ev if e[2] == k and e[3] == 1]
        rep = [e for e in ev if e[2] == k and e[3] > 1]
        curves[("e", k)] = curve_from_events(prim, tgrid, dt, width, ramp, delay)
        if rep:
            curves[("r", k)] = curve_from_events(rep, tgrid, dt, width, ramp, delay)
    total = np.zeros(len(tgrid), dtype=complex)
    for key, c in curves.items():
        if key != "tx":
            total += c
    curves["total"] = total
    res = dict(ifaces=ifaces, tgrid=tgrid, dt=dt, curves=curves, amp=A, width=width, ramp=ramp, delay=delay, f_hz=f_hz,
               events=ev, truncated=trunc, n=n, names=names)
    # table rows: one per curve that exists
    rows = []
    gates = opts.get("gates", [])
    gwin = {}
    res["gate_t"] = {}
    for gt in gates:
        gt0, gt1 = width + ECHO_STEP_NS * gt["a"], width + ECHO_STEP_NS * (gt["b"] + 1)
        a0 = int(round(gt0 / dt))
        gwin[gt["idx"]] = (a0, max(int(round(gt1 / dt)), a0 + 1))
        res["gate_t"][gt["idx"]] = (gt0, gt1)
    supports = {}
    for key in [("e", k) for k in range(1, n + 2)] + [("r", k) for k in range(1, n + 2)] + ["total"]:
        if key not in curves:
            continue
        mag = np.abs(curves[key]) * A
        pk = float(mag.max()) if len(mag) else 0.0
        info = dict(key=key, peak=pk)
        if pk <= 1e-9:
            info.update(start=None, end=None, steps="-", flat="-", gates={g: 0.0 for g in gwin})
            rows.append(info)
            continue
        idx = np.where(mag >= ECHO_SUPPORT_FRAC * pk)[0]
        info["start"], info["end"] = tgrid[idx[0]], tgrid[idx[-1]]
        st, fl = [], []
        sup = mag >= ECHO_SUPPORT_FRAC * pk
        fls = mag >= ECHO_FLAT_FRAC * pk
        for s_ in range(0, ECHO_MAX_STEP + 1):
            a0 = int(round((width + ECHO_STEP_NS * s_) / dt))
            a1 = int(round((width + ECHO_STEP_NS * (s_ + 1)) / dt))
            if a0 >= len(mag):
                break
            if sup[a0:max(a1, a0 + 1)].any():
                st.append(s_)
            if fls[a0:max(a1, a0 + 1)].all():
                fl.append(s_)
        info["steps"], info["flat"] = ranges_text(st), ranges_text(fl)
        info["stepset"] = set(st)
        info["gates"] = {g: (float(np.abs(curves[key][i0:i1].mean()) * A) if i1 <= len(mag) else 0.0) for g, (i0, i1) in gwin.items()}
        if key != "total":
            supports[key] = set(st)
        rows.append(info)
    res["rows"] = rows
    res["gate_total"] = {g: (float(np.abs(total[i0:i1].mean()) * A) if i1 <= len(total) else 0.0) for g, (i0, i1) in gwin.items()}
    # which echoes overlap each other, in gate steps
    ov = []
    keys = [r["key"] for r in rows if r.get("stepset") and r["key"] != "total"]
    lab = {("e", i["k"]): f"echo {i['k']} ({i['short']})" for i in ifaces}
    lab.update({("r", i["k"]): f"repeats of {i['k']}" for i in ifaces})
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            common = supports[keys[i]] & supports[keys[j]]
            if common:
                ov.append((lab[keys[i]], lab[keys[j]], ranges_text(common)))
    res["overlaps"] = ov
    res["labels"] = lab
    # in the gate: which curves are present
    return res


def rf_wave(res, key, t0, t1, npts_per_cycle=24):
    """Carrier waveform of one curve in [t0, t1] ns (the curve must be a complex envelope on res['tgrid'])."""
    f = res["f_hz"] * 1e-9
    dt = 1.0 / (f * npts_per_cycle)
    t = np.arange(t0, t1, dt)
    env = res["curves"][key]
    re = np.interp(t, res["tgrid"], env.real)
    im = np.interp(t, res["tgrid"], env.imag)
    return t, res["amp"] * (re * np.cos(2 * np.pi * f * t) - im * np.sin(2 * np.pi * f * t))


def nice_ticks(lo, hi, target=6):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(target, 1)
    mag = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    first = np.ceil(lo / step - 1e-9) * step
    out, x = [], first
    while x <= hi + 1e-9:
        out.append(round(float(x), 10) + 0.0)
        x += step
    return out
# ---------------------------------------------------------------------------------------------------------------------
# pulse and echo simulator: the tab
# ---------------------------------------------------------------------------------------------------------------------
ECHO_GATE_COLORS = ["#4a3aa7", "#e34948", "#8d5524"]               # gate 1, 2, 3 (distinct from the six echo colours)


class Tip:
    """A small text box that appears while the mouse is over a widget."""

    def __init__(self, widget, text):
        self.w, self.text, self.tw = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _e=None):
        if self.tw is not None:
            return
        x = self.w.winfo_rootx() + 16
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tw = tw = tk.Toplevel(self.w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, justify="left", bg="#fffbe6", relief="solid", bd=1, padx=7, pady=4, wraplength=320).pack()

    def hide(self, _e=None):
        if self.tw is not None:
            self.tw.destroy()
            self.tw = None


def help_icon(parent, text):
    lab = tk.Label(parent, text="?", width=2, bg="#8a8984", fg="white", cursor="question_arrow")
    Tip(lab, text)
    return lab


def _tint(hexcol, f):
    """Colour blended with white (f = 1 keeps the colour, 0 gives white)."""
    c = [int(hexcol[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(255 - (255 - x) * f) for x in c)


class PopPlot(tk.Toplevel):
    """The plot in a window of its own (resizable)."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.title("Pulse and echo plot")
        self.geometry("1250x740")
        self.geom = {}
        self._size = (1250, 700)
        self.lbl = tk.Label(self, bg="white", anchor="nw", bd=0, cursor="crosshair")
        self.lbl.pack(fill="both", expand=True)
        self.readout = ttk.Label(self, text="", font=tab.fnt)
        self.readout.pack(fill="x", padx=8, pady=3)
        self.lbl.bind("<Configure>", self._cfg)
        self.lbl.bind("<Motion>", lambda e: self.readout.configure(text=tab.readout_text(e.x, self.geom)))
        self.lbl.bind("<Leave>", lambda e: self.readout.configure(text=""))
        self._photo = None

    def _cfg(self, e):
        self._size = (max(e.width, 300), max(e.height, 200))
        self.refresh()

    def refresh(self):
        if self.tab.res is None:
            return
        W, H = self._size
        self._photo = ImageTk.PhotoImage(self.tab.render(W, H, geom=self.geom))
        self.lbl.configure(image=self._photo)


class PopTable(tk.Toplevel):
    """The echo table in a window of its own."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.title("Echo table")
        self.geometry("1250x420")
        fr = ttk.Frame(self, padding=6)
        fr.pack(fill="both", expand=True)
        fr.columnconfigure(0, weight=1)
        fr.rowconfigure(0, weight=1)
        self.tree = tab._make_tree(fr)
        self.refresh()

    def refresh(self):
        self.tab._fill_tree(self.tree)


class EchoTab(ttk.Frame):
    """Transmit pulse and the echoes from every interface of a layered chip, with up to three gate windows drawn on top, so the
    right sampling time can be chosen before imaging."""
    INK, INK2, GRID, TXCOL, TOTCOL = "#0b0b0b", "#52514e", "#e6e5e1", "#52514e", "#0b0b0b"
    COLS = [("echo", "Echo", 230, "w"), ("r", "R", 80, "e"), ("rt", "Round trip (ns)", 130, "e"), ("t0", "Start (ns)", 100, "e"),
            ("t1", "End (ns)", 100, "e"), ("pk", "Peak (V)", 100, "e"), ("db", "dB", 80, "e"), ("st", "Gate steps", 170, "w"),
            ("fl", "Flat top steps", 150, "w"), ("g1", "Gate 1 (mV)", 120, "e"), ("g2", "Gate 2 (mV)", 120, "e"),
            ("g3", "Gate 3 (mV)", 120, "e")]

    def __init__(self, parent, app_vars=None):
        super().__init__(parent, padding=8)
        self.av = app_vars
        self.vars = {}
        self.res = None
        self.view = None
        self._job = None
        self._photo = None
        self._geom = {}
        self._size = (700, 420)
        self._loading = False
        self.rows_w = {}
        self.pops = []
        self.table_pop = None
        base = tkfont.nametofont("TkDefaultFont")
        self.fnt = tkfont.Font(family=base.cget("family"), size=base.cget("size") + 2)
        st = ttk.Style()
        st.configure("Big.TCheckbutton", font=self.fnt)
        st.configure("Echo.Treeview", font=self.fnt, rowheight=int(self.fnt.metrics("linespace") * 1.3))
        st.configure("Echo.Treeview.Heading", font=self.fnt)
        self._build()
        self.load_example(0)

    # ---- variables ---------------------------------------------------------------------------------------------
    def sv(self, name, value=""):
        self.vars[name] = tk.StringVar(value=str(value))
        return self.vars[name]

    def bv(self, name, value=False):
        self.vars[name] = tk.BooleanVar(value=value)
        return self.vars[name]

    def g(self, name):
        return self.vars[name].get()

    # ---- layout ------------------------------------------------------------------------------------------------
    def _build(self):
        names = [m[0] for m in ECHO_MATERIALS] + [ECHO_CUSTOM]
        self.sv("n", 4)
        self.bv("att", False)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        # --- stack (top left)
        f = ttk.LabelFrame(top, text="Stack", padding=6)
        f.grid(row=0, column=0, sticky="nw")
        bar = ttk.Frame(f)
        bar.grid(row=0, column=0, columnspan=9, sticky="w", pady=(0, 5))
        ttk.Label(bar, text="Layers above the silicon").pack(side="left")
        ttk.Spinbox(bar, from_=0, to=ECHO_MAX_LAYERS, width=3, textvariable=self.vars["n"], command=self._rows_changed).pack(side="left", padx=(5, 12))
        self.vars["n"].trace_add("write", lambda *a: self._rows_changed())
        ttk.Checkbutton(bar, text="Include attenuation", variable=self.vars["att"]).pack(side="left", padx=(0, 14))
        ttk.Label(bar, text="Example").pack(side="left")
        self.cb_ex = ttk.Combobox(bar, values=[e[0] for e in ECHO_EXAMPLES], state="readonly", width=24)
        self.cb_ex.pack(side="left", padx=5)
        self.cb_ex.current(0)
        ttk.Button(bar, text="Load", width=6, command=lambda: self.load_example(self.cb_ex.current())).pack(side="left")
        ttk.Button(bar, text="Save ...", width=8, command=self.save_json).pack(side="left", padx=(12, 4))
        ttk.Button(bar, text="Open ...", width=8, command=self.open_json).pack(side="left")
        heads = ["", "Material", "Name", "Z (MRayl)", "c (m/s)", "Thickness", "", "Atten. (dB/mm, 1 GHz)"]
        for c, h in enumerate(heads):
            ttk.Label(f, text=h, foreground=self.INK2).grid(row=1, column=c, sticky="w", padx=(0, 6))
        for i in range(ECHO_MAX_LAYERS + 1):
            self._layer_row(f, i, names)
        self._top_row(f, names)
        # --- pulse (top right)
        b = ttk.LabelFrame(top, text="Pulse", padding=8)
        b.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._field(b, 0, 0, "Frequency (GHz)", "f", "1.85", single=True, lw=16)
        self._field(b, 1, 0, "Amplitude (V)", "amp", "1", single=True, lw=16)
        self._field(b, 2, 0, "Pulse width (ns)", "w", PULSE_DEFAULT_NS, single=True, lw=16)
        self._field(b, 3, 0, "Ramp (ns)", "ramp", "10", single=True, lw=16, tip="Rise time and fall time, both inside the pulse width.")
        self._field(b, 4, 0, "Extra delay (ns)", "delay", "0", single=True, lw=16, tip="Added to every echo (cables, electronics).")
        ttk.Button(b, text="Copy from Acquire tab", command=self.copy_from_acquire).grid(row=5, column=0, sticky="w", pady=(6, 0))
        # --- bottom: left controls | plot and table
        bot = ttk.Frame(self)
        bot.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        bot.columnconfigure(1, weight=1)
        bot.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        left = ttk.Frame(bot)
        left.grid(row=0, column=0, sticky="nw")
        b = ttk.LabelFrame(left, text="Sampling gates", padding=6)
        b.grid(row=0, column=0, sticky="ew")
        self.gate_lbl = []
        for i in range(1, 4):
            r = (i - 1) * 2
            self.bv(f"gon{i}", i == 1)
            fr = ttk.Frame(b)
            fr.grid(row=r, column=0, sticky="w", pady=(0 if i == 1 else 5, 0))
            tk.Label(fr, bg=ECHO_GATE_COLORS[i - 1], width=2).pack(side="left", padx=(0, 4))
            ttk.Checkbutton(fr, text=f"Gate {i}", variable=self.vars[f"gon{i}"]).pack(side="left")
            ttk.Label(fr, text="from step").pack(side="left", padx=(10, 3))
            ttk.Entry(fr, textvariable=self.sv(f"ga{i}", FIRST_ECHO_STEP), width=5).pack(side="left")
            ttk.Label(fr, text="to step").pack(side="left", padx=(8, 3))
            ttk.Entry(fr, textvariable=self.sv(f"gb{i}", FIRST_ECHO_STEP), width=5).pack(side="left")
            lab = ttk.Label(b, text="", foreground=self.INK2)
            lab.grid(row=r + 1, column=0, sticky="w", padx=(26, 0))
            self.gate_lbl.append(lab)
        b = ttk.LabelFrame(left, text="Reflections", padding=6)
        b.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.bv("multi", False)
        ttk.Checkbutton(b, text="Include multiple reflections", variable=self.vars["multi"]).grid(row=0, column=0, columnspan=3, sticky="w")
        self._field(b, 1, 0, "Reflection at the transducer", "rb", "0.8", w=6, tip="Fraction of the pressure wave that is reflected "
                    "again when an echo returns to the transducer. It sets how strong the repeated echoes of the die are.", single=True)
        self._field(b, 2, 0, "Ignore echoes below (% of transmit)", "amin", "1", w=6, single=True)
        b = ttk.LabelFrame(left, text="Time axis", padding=6)
        b.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._field(b, 0, 0, "From (ns)", "x0", "0", w=7, single=True)
        self._field(b, 1, 0, "To (ns)", "x1", "1000", w=7, single=True)
        self._field(b, 2, 0, "Largest amplitude (V)", "ymax", "", w=7, single=True, tip="Leave empty for an automatic axis.")
        # --- right: plot with its line switches (top), table and notes (bottom); the divider can be dragged
        rt = ttk.PanedWindow(bot, orient="vertical")
        rt.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.paned = rt
        self._sash_done = False
        rt.bind("<Configure>", self._place_sash)
        up = ttk.Frame(rt)
        up.columnconfigure(0, weight=1)
        up.rowconfigure(0, weight=1)
        rt.add(up, weight=5)
        self.plot = tk.Label(up, bd=1, relief="solid", anchor="nw", bg="white", cursor="crosshair")
        self.plot.grid(row=0, column=0, sticky="nsew")
        self.plot.bind("<Configure>", self._plot_resized)
        self.plot.bind("<Motion>", lambda e: self.readout.configure(text=self.readout_text(e.x, self._geom)))
        self.plot.bind("<Leave>", lambda e: self.readout.configure(text=""))
        self.readout = ttk.Label(up, text="", foreground=self.INK2)
        self.readout.grid(row=1, column=0, sticky="w", pady=(2, 0))
        sw = ttk.LabelFrame(up, text="Plot lines", padding=6)
        sw.grid(row=0, column=1, rowspan=2, sticky="n", padx=(8, 0))
        self.sw_frame = sw
        self.bv("show_tx", True)
        self.bv("show_total", True)
        self.bv("show_rep", True)
        self.sw_items = {}
        self.sw_items["tx"] = self._switch("show_tx", "Transmit", self.TXCOL)
        for k in range(1, ECHO_MAX_LAYERS + 2):
            self.bv(f"show{k}", True)
            self.sw_items[k] = self._switch(f"show{k}", f"{k}", ECHO_COLORS[(k - 1) % len(ECHO_COLORS)])
        self.sw_items["rep"] = self._switch("show_rep", "Repeats (dashed)", "#8a8984")
        self.sw_items["total"] = self._switch("show_total", "Total of all echoes", self.TOTCOL)
        self.btn_pop_plot = ttk.Button(sw, text="Pop out plot", command=self.pop_plot)
        low = ttk.Frame(rt)
        low.columnconfigure(0, weight=1)
        low.rowconfigure(0, weight=1)
        rt.add(low, weight=3)
        tbf = ttk.Frame(low)
        tbf.grid(row=0, column=0, sticky="nsew")
        tbf.columnconfigure(0, weight=1)
        tbf.rowconfigure(0, weight=1)
        self.tree = self._make_tree(tbf)
        nf = ttk.Frame(low)
        nf.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        nf.columnconfigure(0, weight=1)
        self.notes = tk.Text(nf, height=3, wrap="word", relief="solid", bd=1)
        self.notes.grid(row=0, column=0, sticky="ew")
        ns = ttk.Scrollbar(nf, command=self.notes.yview)
        ns.grid(row=0, column=1, sticky="ns")
        self.notes.configure(yscrollcommand=ns.set)
        self.notes.configure(state="disabled")
        bt = ttk.Frame(low)
        bt.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.status = ttk.Label(bt, text="", foreground="#a33")
        self.status.pack(side="left")
        help_icon(bt, "Echo amplitudes are relative to the transmit amplitude. Transducer conversion loss, electronics and "
                      "diffraction are not included.").pack(side="right", padx=(6, 0))
        ttk.Button(bt, text="Export CSV ...", command=self.export_csv).pack(side="right")
        ttk.Button(bt, text="Save plot ...", command=self.save_png).pack(side="right", padx=6)
        ttk.Button(bt, text="Pop out table", command=self.pop_table).pack(side="right")
        for name, var in self.vars.items():
            if name != "n":
                var.trace_add("write", self._changed)
        self.vars["n"].trace_add("write", self._changed)

    def _field(self, parent, r, c, label, key, default, w=7, tip=None, single=False, lw=0):
        """label + entry (+ a ? that explains it) in cell (r, c); single = one field per row of the parent."""
        fr = ttk.Frame(parent)
        fr.grid(row=r, column=c if not single else 0, sticky="w", padx=(0 if c == 0 else 12, 0), pady=1)
        ttk.Label(fr, text=label, width=lw).pack(side="left", padx=(0, 4))
        ttk.Entry(fr, textvariable=self.sv(key, default), width=w).pack(side="left")
        if tip:
            help_icon(fr, tip).pack(side="left", padx=(5, 0))
        return fr

    def _switch(self, key, text, color):
        fr = ttk.Frame(self.sw_frame)
        tk.Label(fr, bg=color, width=3, height=1).pack(side="left", pady=3)
        cbx = ttk.Checkbutton(fr, text=text, variable=self.vars[key], style="Big.TCheckbutton")
        cbx.pack(side="left", padx=(6, 0))
        return fr, cbx

    def _make_tree(self, parent):
        tree = ttk.Treeview(parent, columns=[c[0] for c in self.COLS], show="headings", height=4, style="Echo.Treeview")
        for key, head, w, anc in self.COLS:
            tree.heading(key, text=head, anchor=anc)
            tree.column(key, width=w, anchor=anc, stretch=False, minwidth=40)
        tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        vs.grid(row=0, column=1, sticky="ns")
        hs = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        hs.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        return tree

    def _layer_row(self, f, i, names):
        r = 2 + i
        pre = f"L{i}_"
        lab = ttk.Label(f, text="Silicon (base)" if i == 0 else f"Layer {i}")
        lab.grid(row=r, column=0, sticky="w", padx=(0, 8), pady=1)
        mat = ttk.Combobox(f, values=names, state="readonly", width=17, textvariable=self.sv(pre + "mat", "Silicon"))
        name = ttk.Entry(f, textvariable=self.sv(pre + "name", "Silicon"), width=14)
        z = ttk.Entry(f, textvariable=self.sv(pre + "z", "19.64"), width=8)
        c = ttk.Entry(f, textvariable=self.sv(pre + "c", "8433"), width=8)
        th = ttk.Entry(f, textvariable=self.sv(pre + "th", ECHO_BASE_THICK_UM if i == 0 else ""), width=9)
        if i == 0:
            un = ttk.Label(f, text="um")
            self.sv(pre + "unit", "um")
        else:
            un = ttk.Combobox(f, values=list(ECHO_UNITS), state="readonly", width=4, textvariable=self.sv(pre + "unit", "um"))
        al = ttk.Entry(f, textvariable=self.sv(pre + "al", "0.2"), width=8)
        ws = [lab, mat, name, z, c, th, un, al]
        for col, w in enumerate(ws):
            if col:
                w.grid(row=r, column=col, sticky="w", padx=(0, 6), pady=1)
        mat.bind("<<ComboboxSelected>>", lambda e, i=i: self._apply_material(i))
        self.rows_w[i] = ws
        if i == 0:
            self.al_widgets = [al]
        else:
            self.al_widgets.append(al)

    def _top_row(self, f, names):
        r = 2 + ECHO_MAX_LAYERS + 1
        lab = ttk.Label(f, text="Top (infinite)")
        lab.grid(row=r, column=0, sticky="w", padx=(0, 8), pady=(3, 0))
        mat = ttk.Combobox(f, values=names, state="readonly", width=17, textvariable=self.sv("T_mat", "Air"))
        name = ttk.Entry(f, textvariable=self.sv("T_name", "Air"), width=14)
        z = ttk.Entry(f, textvariable=self.sv("T_z", "0.0004"), width=8)
        for col, w in ((1, mat), (2, name), (3, z)):
            w.grid(row=r, column=col, sticky="w", padx=(0, 6), pady=(3, 0))
        mat.bind("<<ComboboxSelected>>", lambda e: self._apply_material("T"))

    def _apply_material(self, i):
        pre = "T_" if i == "T" else f"L{i}_"
        m = echo_material(self.g(pre + "mat"))
        if m is None:                                                  # Custom: leave the numbers for the user
            return
        self._loading = True
        self.vars[pre + "name"].set(m[0])
        self.vars[pre + "z"].set("%g" % m[1])
        if i != "T":
            self.vars[pre + "c"].set("%g" % m[2])
            self.vars[pre + "al"].set("%g" % m[3])
        self._loading = False
        self._changed()

    def _rows_changed(self):
        try:
            n = int(float(self.g("n")))
        except (ValueError, tk.TclError):
            return
        n = max(0, min(ECHO_MAX_LAYERS, n))
        for i in range(1, ECHO_MAX_LAYERS + 1):
            for col, w in enumerate(self.rows_w[i]):
                if i <= n:
                    w.grid()
                else:
                    w.grid_remove()
        self._update_alpha_state()

    def _update_alpha_state(self):
        st = "normal" if self.g("att") else "disabled"
        for w in self.al_widgets:
            w.configure(state=st)

    # ---- load / save -------------------------------------------------------------------------------------------
    def load_example(self, idx):
        name, base, layers, topm = ECHO_EXAMPLES[idx]
        self._loading = True
        self.vars["n"].set(len(layers))
        self.vars["L0_th"].set("%g" % base)
        self._set_layer(0, "Silicon", "Silicon")
        for i in range(1, ECHO_MAX_LAYERS + 1):
            if i <= len(layers):
                mat, nm, th, un = layers[i - 1]
                self._set_layer(i, mat, nm)
                self.vars[f"L{i}_th"].set("%g" % th)
                self.vars[f"L{i}_unit"].set(un)
            else:
                self._set_layer(i, "Silicon", "Silicon")
                self.vars[f"L{i}_th"].set("")
                self.vars[f"L{i}_unit"].set("um")
        self.vars["T_mat"].set(topm)
        m = echo_material(topm)
        self.vars["T_name"].set(topm)
        self.vars["T_z"].set("%g" % m[1])
        self._loading = False
        self._rows_changed()
        self._changed()

    def _set_layer(self, i, mat, nm):
        m = echo_material(mat)
        pre = f"L{i}_"
        self.vars[pre + "mat"].set(mat)
        self.vars[pre + "name"].set(nm)
        self.vars[pre + "z"].set("%g" % m[1])
        self.vars[pre + "c"].set("%g" % m[2])
        self.vars[pre + "al"].set("%g" % m[3])

    def get_state(self):
        return {k: v.get() for k, v in self.vars.items()}

    def set_state(self, d):
        self._loading = True
        for k, v in d.items():
            if k in self.vars:
                try:
                    v2 = self.vars[k]
                    v2.set(bool(v) if isinstance(v2, tk.BooleanVar) else str(v))
                except Exception:
                    pass
        self._loading = False
        self._rows_changed()
        self._changed()

    def save_json(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Stack", "*.json")], initialfile="stack.json")
        if p:
            with open(p, "w") as f:
                json.dump(self.get_state(), f, indent=1)

    def open_json(self):
        p = filedialog.askopenfilename(filetypes=[("Stack", "*.json")])
        if p:
            try:
                with open(p) as f:
                    self.set_state(json.load(f))
            except Exception as e:
                messagebox.showwarning("Open stack", f"Cannot read {p}: {e}")

    def copy_from_acquire(self):
        a = self.av
        if not a:
            return
        try:
            self.vars["f"].set("%g" % (float(a["freq"].get()) / 1000.0))
            self.vars["w"].set(str(int(float(a["width"].get()))))
            mode = MODE_OF.get(a["mode"].get(), MODE_LIVE)
            if mode in (MODE_SNH, MODE_CONT):
                lo, hi = int(float(a["step_start"].get())), int(float(a["step_end"].get()))
            else:
                lo = hi = int(float(a["step_live"].get()))
            self.vars["gon1"].set(True)
            self.vars["ga1"].set(str(lo))
            self.vars["gb1"].set(str(hi))
        except ValueError:
            self.status.configure(text="The Acquire tab has a value that is not a number.")

    # ---- reading the inputs ------------------------------------------------------------------------------------
    def _num(self, key, label, lo=None, hi=None, blank=None):
        s = str(self.g(key)).strip()
        if s == "" and blank is not None:
            return blank
        try:
            x = float(s)
        except ValueError:
            raise ValueError(f"{label}: enter a number")
        if lo is not None and x < lo or hi is not None and x > hi:
            raise ValueError(f"{label}: must be between {lo} and {hi}")
        return x

    def collect(self):
        n = int(max(0, min(ECHO_MAX_LAYERS, float(self.g("n")))))
        att = bool(self.g("att"))
        stack = []
        for i in range(n + 1):
            pre = f"L{i}_"
            lab = "Silicon (base)" if i == 0 else f"Layer {i}"
            z = self._num(pre + "z", f"{lab} Z", 1e-6, 1e4)
            c = self._num(pre + "c", f"{lab} speed of sound", 1.0, 5e4)
            th = self._num(pre + "th", f"{lab} thickness (required)", 1e-6, 1e9)
            th_m = th * ECHO_UNITS[self.g(pre + "unit")]
            al = self._num(pre + "al", f"{lab} attenuation", 0, 1e6) if att else 0.0
            stack.append(dict(name=self.g(pre + "name").strip() or lab, z=z, c=c, thick=th_m, alpha=al))
        top = dict(name=self.g("T_name").strip() or "Top", z=self._num("T_z", "Top medium Z", 1e-6, 1e4))
        f = self._num("f", "Frequency", 0.05, 20)
        pulse = dict(f_ghz=f, amp=self._num("amp", "Amplitude", 1e-6, 1e3), width=self._num("w", "Pulse width", 5, 5000),
                     ramp=self._num("ramp", "Ramp", 0, 2500), delay=self._num("delay", "Extra delay", 0, 1e5))
        gates = []
        for i in range(1, 4):
            if self.g(f"gon{i}"):
                a = int(self._num(f"ga{i}", f"Gate {i} from step", 0, ECHO_MAX_STEP))
                b = int(self._num(f"gb{i}", f"Gate {i} to step", 0, ECHO_MAX_STEP))
                if b < a:
                    raise ValueError(f"Gate {i}: 'to' step must not be below 'from' step")
                gates.append(dict(idx=i, a=a, b=b))
        opts = dict(att=att, multi=bool(self.g("multi")), rb=self._num("rb", "Reflection at the transducer", -1, 1),
                    amin_pct=self._num("amin", "Ignore echoes below", 0.01, 50), gates=gates)
        x0 = self._num("x0", "Time from", 0, 1e5)
        x1 = self._num("x1", "Time to", 1, 1e5)
        if x1 <= x0:
            raise ValueError("Time axis: 'to' must be larger than 'from'")
        ymax = self._num("ymax", "Largest amplitude", 1e-9, 1e6, blank=0.0)
        return stack, top, pulse, opts, dict(x0=x0, x1=x1, ymax=ymax)

    # ---- update ------------------------------------------------------------------------------------------------
    def _changed(self, *a):
        if self._loading:
            return
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(150, self.update_plot)

    def update_plot(self):
        self._job = None
        self._update_alpha_state()
        self._gate_labels()
        try:
            stack, top, pulse, opts, view = self.collect()
        except (ValueError, tk.TclError) as e:
            self.status.configure(text=str(e))
            return
        self.res = echo_simulate(stack, top, pulse, opts, xmax_ns=view["x1"])
        self.view = view
        self.status.configure(text="Too many reflections: some of the smallest were left out. Raise 'Ignore echoes below'."
                              if self.res["truncated"] else "")
        self._switch_layout()
        self._fill_tree(self.tree)
        self._notes()
        self._draw()
        if self.table_pop is not None and self.table_pop.winfo_exists():
            self.table_pop.refresh()

    def _gate_labels(self):
        for i in range(1, 4):
            try:
                a, b = int(float(self.g(f"ga{i}"))), int(float(self.g(f"gb{i}")))
                self.gate_lbl[i - 1].configure(text=f"{ECHO_STEP_NS * a:g} to {ECHO_STEP_NS * (b + 1):g} ns after TX closes")
            except (ValueError, tk.TclError):
                self.gate_lbl[i - 1].configure(text="")

    def _switch_layout(self):
        res = self.res
        n = res["n"]
        for k in range(1, ECHO_MAX_LAYERS + 2):
            if k <= n + 1:
                self.sw_items[k][1].configure(text=f"{k}  {res['ifaces'][k - 1]['short']}")
        shown = [self.sw_items["tx"]] + [self.sw_items[k] for k in range(1, n + 2)]
        if self.g("multi"):
            shown.append(self.sw_items["rep"])
        shown.append(self.sw_items["total"])
        for it in self.sw_items.values():
            it[0].grid_forget()
        for j, it in enumerate(shown):
            it[0].grid(row=j, column=0, sticky="w", pady=1)
        self.btn_pop_plot.grid(row=len(shown), column=0, sticky="ew", pady=(8, 0))

    def _table_rows(self):
        res = self.res
        A = res["amp"]
        out = []
        for row in res["rows"]:
            key = row["key"]
            if row["peak"] < 1e-6 * A:
                continue
            if key == "total":
                name, R, rt = "Total of all echoes", "", ""
            else:
                kind, k = key
                i = res["ifaces"][k - 1]
                name = i["label"] if kind == "e" else f"      repeats of {k}"
                R = f"{i['R']:+.3f}" if kind == "e" else ""
                rt = f"{i['rt']:.1f}" if kind == "e" else ""
            db = 20 * np.log10(row["peak"] / A)
            gv = [(f"{row['gates'][g] * 1000:.1f}" if g in row["gates"] else "") for g in (1, 2, 3)]
            out.append((name, R, rt, f"{row['start']:.1f}", f"{row['end']:.1f}", f"{row['peak']:.4f}", f"{db:.1f}", row["steps"],
                        row["flat"]) + tuple(gv))
        return out

    def _fill_tree(self, tree):
        tree.delete(*tree.get_children())
        for vals in self._table_rows():
            tree.insert("", "end", values=vals)
        base = ["echo", "r", "rt", "t0", "t1", "pk", "db", "st", "fl"]
        on = [f"g{i}" for i in range(1, 4) if self.g(f"gon{i}")]
        tree.configure(displaycolumns=base + on)

    def _notes(self):
        res = self.res
        A = res["amp"]
        lines = []
        for i in range(1, 4):
            if not self.g(f"gon{i}") or i not in res["gate_t"]:
                continue
            a, b = int(float(self.g(f"ga{i}"))), int(float(self.g(f"gb{i}")))
            inside = []
            for row in res["rows"]:
                if row["key"] == "total" or row["gates"].get(i, 0.0) < 0.005 * A:
                    continue
                kind, k = row["key"]
                inside.append(f"{k} {res['ifaces'][k - 1]['short']}{'' if kind == 'e' else ' (repeat)'} {row['gates'][i] * 1000:.1f} mV")
            head = f"Gate {i} ({'step %d' % a if a == b else 'steps %d to %d' % (a, b)}): "
            lines.append(head + (";  ".join(inside) + f".  Sum {res['gate_total'][i] * 1000:.1f} mV." if inside else "no echo reaches it."))
        if res["overlaps"]:
            lines.append("Echoes present at the same time (gate steps where both are above 5 % of their own peak):")
            for a, b, st in res["overlaps"][:8]:
                lines.append(f"   {a}  and  {b}:  steps {st}")
            if len(res["overlaps"]) > 8:
                lines.append(f"   ... and {len(res['overlaps']) - 8} more pairs")
        else:
            lines.append("No two echoes overlap in time.")
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", "\n".join(lines))
        self.notes.configure(state="disabled")

    # ---- pop-outs ----------------------------------------------------------------------------------------------
    def pop_plot(self):
        pp = PopPlot(self)
        self.pops = [p for p in self.pops if p.winfo_exists()] + [pp]

    def pop_table(self):
        if self.table_pop is not None and self.table_pop.winfo_exists():
            self.table_pop.lift()
            return
        self.table_pop = PopTable(self)

    # ---- drawing -----------------------------------------------------------------------------------------------
    def _place_sash(self, e):
        """Give the plot about 60 % of the height the first time the tab has a size; the divider can be dragged afterwards."""
        if self._sash_done or e.height < 300:
            return
        try:
            self.paned.sashpos(0, int(e.height * 0.58))
            self._sash_done = True
        except tk.TclError:
            pass

    def _plot_resized(self, e):
        w, h = max(e.width - 2, 300), max(e.height - 2, 200)
        if (w, h) != self._size:
            self._size = (w, h)
            self._draw()

    def _draw(self):
        if self.res is None:
            return
        W, H = self._size
        self._photo = ImageTk.PhotoImage(self.render(W, H, geom=self._geom))
        self.plot.configure(image=self._photo)
        self.pops = [p for p in self.pops if p.winfo_exists()]
        for p in self.pops:
            p.refresh()

    def _visible(self):
        res = self.res
        out = []
        if self.g("show_tx"):
            out.append(("tx", self.TXCOL, "Transmit", False, 3))
        for k in range(1, res["n"] + 2):
            if self.g(f"show{k}"):
                col = ECHO_COLORS[(k - 1) % len(ECHO_COLORS)]
                out.append((("e", k), col, f"{k}  {res['ifaces'][k - 1]['short']}", False, 3))
                if ("r", k) in res["curves"] and self.g("show_rep") and self.g("multi"):
                    out.append((("r", k), col, "", True, 3))              # dashed repeats are drawn but not listed in the legend
        if self.g("show_total"):
            out.append(("total", self.TOTCOL, "Total", False, 2))
        return out

    def render(self, W, H, S=2, geom=None):
        res, view = self.res, self.view
        A = res["amp"]
        x0, x1 = view["x0"], view["x1"]
        vis = self._visible()
        u = max(1.0, min(W / 950.0, H / 560.0, 1.8))                  # everything grows with the window (pop-out)
        img = Image.new("RGB", (int(W * S), int(H * S)), "white")
        dr = ImageDraw.Draw(img)

        def F(sz):
            return font(int(sz * u * S))
        # legend band at the bottom: the lines, TX closes / RX opens, the gates
        ents = [("line", col, text) for key, col, text, dashed, wd in vis if text]
        ents.append(("vdash", "#6f6e69", "TX closes, RX opens"))
        for gt in res["gate_t"]:
            a, b = int(float(self.g(f"ga{gt}"))), int(float(self.g(f"gb{gt}")))
            ents.append(("box", ECHO_GATE_COLORS[gt - 1], f"Gate {gt}  step {a}" if a == b else f"Gate {gt}  steps {a} to {b}"))
        rowh = int(26 * u)
        lx, ly, placed = int(14 * u), 0, []
        for kind, col, text in ents:
            wlen = 34 * u + dr.textlength(text, font=F(14)) / S
            if lx + wlen > W - 10 and lx > 14 * u:
                lx, ly = int(14 * u), ly + rowh
            placed.append((lx, ly, kind, col, text))
            lx += wlen + 18 * u
        leg_h = ly + rowh + int(8 * u)
        l, r, t, b = int(92 * u), W - int(20 * u), int(46 * u), H - leg_h - int(64 * u)
        b = max(b, t + 60)
        ymax = view["ymax"]
        if ymax <= 0:
            m = 0.0
            for key, *_ in vis:
                m = max(m, float(np.abs(res["curves"][key])[int(x0 / res["dt"]):int(x1 / res["dt"]) + 1].max(initial=0.0)) * A)
            ymax = max(m * 1.14, 0.02 * A)
        y0, y1 = 0.0, ymax

        def X(v):
            return (l + (v - x0) / (x1 - x0) * (r - l)) * S

        def Y(v):
            return (b - (v - y0) / (y1 - y0) * (b - t)) * S
        # gate bands (behind everything)
        for gt, (ga, gb) in res["gate_t"].items():
            if gb >= x0 and ga <= x1:
                col = ECHO_GATE_COLORS[gt - 1]
                gx0, gx1 = X(max(ga, x0)), X(min(gb, x1))
                if gx1 - gx0 < 5 * S:
                    gx1 = gx0 + 5 * S
                dr.rectangle([gx0, t * S, gx1, b * S], fill=_tint(col, 0.20))
                dr.line([gx0, t * S, gx0, b * S], fill=col, width=int(1.5 * S))
                dr.line([gx1, t * S, gx1, b * S], fill=col, width=int(1.5 * S))
                dr.text(((gx0 + gx1) / 2, (t + 4 * u) * S), str(gt), fill=col, font=F(14), anchor="mt")
        # grid and axes
        for tv in nice_ticks(x0, x1, 9):
            dr.line([X(tv), t * S, X(tv), b * S], fill=self.GRID, width=S)
            dr.text((X(tv), (b + 6 * u) * S), f"{tv:g}", fill=self.INK2, font=F(15), anchor="mt")
        for yv in nice_ticks(y0, y1, 5):
            dr.line([l * S, Y(yv), r * S, Y(yv)], fill=self.GRID, width=S)
            dr.text(((l - 8 * u) * S, Y(yv)), f"{yv:.3g}", fill=self.INK2, font=F(15), anchor="rm")
        dr.rectangle([l * S, t * S, r * S, b * S], outline="#8a8984", width=S)
        dr.text((((l + r) / 2) * S, (b + 30 * u) * S), "Time after TX opens (ns)", fill=self.INK, font=F(16), anchor="mt")
        self._vtext(img, (16 * u * S, ((t + b) / 2) * S), "Magnitude (V)", F(16), self.INK)
        # gate-step axis on top
        w = res["width"]
        dr.text(((l - 8 * u) * S, (t - 12 * u) * S), "step", fill=self.INK2, font=F(13), anchor="rm")
        for sv_ in nice_ticks(0, ECHO_MAX_STEP, 10):
            tv = w + ECHO_STEP_NS * sv_
            if x0 <= tv <= x1:
                dr.line([X(tv), (t - 5 * u) * S, X(tv), t * S], fill=self.INK2, width=S)
                dr.text((X(tv), (t - 7 * u) * S), f"{sv_:g}", fill=self.INK2, font=F(13), anchor="mb")
        # TX closes / RX opens
        if x0 <= w <= x1:
            self._vline(dr, X(w), t * S, b * S, "#6f6e69", S, 2)
        # curves: transmit, echoes, total on top
        cols = max(int((r - l) * S), 50)
        tt = np.linspace(x0, x1, cols)
        order = ([v for v in vis if v[0] == "tx"] + [v for v in vis if v[0] not in ("tx", "total")]
                 + [v for v in vis if v[0] == "total"])
        for key, col, text, dashed, wd in order:
            yv = np.interp(tt, res["tgrid"], np.abs(res["curves"][key])) * A
            pts = [(X(a), Y(c_)) for a, c_ in zip(tt, yv)]
            self._polyline(dr, pts, col, wd * S * 1.15, dashed, S)
        # the interface number above the peak of every shown first echo
        for key, col, text, dashed, wd in vis:
            if isinstance(key, tuple) and key[0] == "e":
                mag = np.abs(res["curves"][key]) * A
                j0, j1 = int(x0 / res["dt"]), min(int(x1 / res["dt"]) + 1, len(mag))
                if j1 > j0 and mag[j0:j1].max() > 0.03 * ymax:
                    j = j0 + int(np.argmax(mag[j0:j1]))
                    dr.text((X(res["tgrid"][j]), Y(mag[j]) - 4 * u * S), str(key[1]), fill=self.INK, font=F(17), anchor="mb")
        # legend
        base = (H - leg_h + 4 * u) * S
        for lx, ly, kind, col, text in placed:
            yy = base + (ly + rowh / 2) * S
            if kind == "line":
                dr.line([lx * S, yy, (lx + 24 * u) * S, yy], fill=col, width=int(3 * S))
            elif kind == "vdash":
                for k_ in range(3):
                    xx = (lx + 12 * u) * S
                    ya = yy - (11 - k_ * 8) * u * S
                    dr.line([xx, ya, xx, ya + 5 * u * S], fill=col, width=int(2.5 * S))
            else:
                dr.rectangle([lx * S, yy - 8 * u * S, (lx + 22 * u) * S, yy + 8 * u * S], fill=_tint(col, 0.35), outline=col, width=int(1.5 * S))
            dr.text(((lx + 30 * u) * S, yy), text, fill=self.INK, font=F(14), anchor="lm")
        if geom is not None:
            geom.update(l=l, r=r, t=t, b=b, x0=x0, x1=x1)
        return img.resize((W, H), Image.LANCZOS)

    @staticmethod
    def _vtext(img, xy, text, fnt, fill):
        box = fnt.getbbox(text)
        tw, th = box[2] - box[0] + 6, box[3] - box[1] + 6
        tmp = Image.new("RGBA", (tw, th), (255, 255, 255, 0))
        ImageDraw.Draw(tmp).text((3 - box[0], 3 - box[1]), text, fill=fill, font=fnt)
        tmp = tmp.rotate(90, expand=True)
        img.paste(tmp, (int(xy[0] - tmp.width / 2), int(xy[1] - tmp.height / 2)), tmp)

    @staticmethod
    def _vline(dr, x, ya, yb, col, S, wd=1):
        y = ya
        while y < yb:
            dr.line([x, y, x, min(y + 8 * S, yb)], fill=col, width=int(wd * S))
            y += 13 * S

    @staticmethod
    def _polyline(dr, pts, col, wd, dashed, S):
        if len(pts) < 2:
            return
        if not dashed:
            dr.line(pts, fill=col, width=int(wd), joint="curve")
            return
        run = []
        for p in pts:
            if int(p[0] // (8 * S)) % 2 == 0:
                run.append(p)
            else:
                if len(run) > 1:
                    dr.line(run, fill=col, width=int(wd))
                run = []
        if len(run) > 1:
            dr.line(run, fill=col, width=int(wd))

    def readout_text(self, x, geom):
        if self.res is None or not geom:
            return ""
        l, r = geom["l"], geom["r"]
        if not (l <= x <= r):
            return ""
        tv = geom["x0"] + (x - l) / (r - l) * (geom["x1"] - geom["x0"])
        res = self.res
        A, w = res["amp"], res["width"]
        j = max(0, min(int(round(tv / res["dt"])), len(res["tgrid"]) - 1))
        parts = [f"t = {tv:.1f} ns   step {(tv - w) / ECHO_STEP_NS:.1f}"]
        for key, col, text, dashed, wd in self._visible():
            if text:
                parts.append(f"{text.split('  ')[0] if key not in ('tx', 'total') else text}: {abs(res['curves'][key][j]) * A * 1000:.1f} mV")
        return "     ".join(parts)

    # ---- export ------------------------------------------------------------------------------------------------
    def save_png(self):
        if self.res is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")], initialfile="echo_simulation.png")
        if p:
            self.render(1800, 900).save(p)

    def export_csv(self):
        if self.res is None:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="echo_table.csv")
        if not p:
            return
        res = self.res
        with open(p, "w") as f:
            f.write(",".join(c[1] for c in self.COLS) + "\n")
            for vals in self._table_rows():
                f.write(",".join('"%s"' % str(x).strip() for x in vals) + "\n")
        q = os.path.splitext(p)[0] + "_curves.csv"
        keys = ["tx"] + [k for k in res["curves"] if k not in ("tx", "total")] + ["total"]
        step = int(round(1.0 / res["dt"]))
        with open(q, "w") as f:
            f.write("time_ns," + ",".join("transmit" if k == "tx" else ("total" if k == "total" else f"{'echo' if k[0] == 'e' else 'repeats'}_{k[1]}")
                                          for k in keys) + "\n")
            for j in range(0, len(res["tgrid"]), step):
                f.write("%.2f," % res["tgrid"][j] + ",".join("%.6g" % (abs(res["curves"][k][j]) * res["amp"]) for k in keys) + "\n")
TRACE_CAP = 400                                    # sweep points whose frames are kept to redraw the trace
METRICS = ["Mean", "Mean of |x|", "RMS", "Std over pixels", "99th percentile of |x|"]
TIME_XLABEL = "time after TX closes (ns)"


class TimeUp(Cancelled):
    pass


def metric_value(img, name):
    a = np.asarray(img, dtype=np.float64)
    if name == METRICS[0]:
        return float(a.mean())
    if name == METRICS[1]:
        return float(np.abs(a).mean())
    if name == METRICS[2]:
        return float(np.sqrt((a * a).mean()))
    if name == METRICS[3]:
        return float(a.std())
    return float(np.percentile(np.abs(a), 99))


def limits(img, disp):
    """Colour scale of an image from the display settings (dict, so the writer thread can use it too)."""
    try:
        if disp["fixed"]:
            lo, hi = float(disp["vmin"]), float(disp["vmax"])
        else:
            lo, hi = (float(x) for x in np.percentile(img, [disp["plo"], disp["phi"]]))
    except ValueError:
        return 0.0, 1.0
    if not hi > lo:
        hi = lo + 1e-6
    return lo, hi


def sub_text(b):
    """The description under the 2D map: what the image is and where it was taken."""
    parts = []
    lab = b.get("label", "")
    if lab and lab not in ("sample", "live"):
        parts.append(lab)
    if "f" in b:
        parts.append(f"f = {b['f']:g} MHz")
    if "n" in b and not str(lab).startswith("integrated"):
        parts.append(f"gate step {b['n']}")
    parts.append(f"frames averaged = {b.get('roll_have', 1)}")
    return "    ".join(parts)


def sanitize(s):
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in s.strip().replace(" ", "_"))


def auto_tag(cfg):
    p = cfg["points"]
    f0, n0 = p[0]
    m = cfg["mode"]
    if m == MODE_LIVE:
        rng = f"{f0:g}MHz_step{n0}"
    elif m == MODE_FREQ:
        rng = f"{p[0][0]:g}-{p[-1][0]:g}MHz_step{n0}"
    else:
        rng = f"{f0:g}MHz_step{n0}-{p[-1][1]}"
    return MODE_NAME[m] + "_" + rng


# ---------------------------------------------------------------------------------------------------------------------
# air reference (background)
# ---------------------------------------------------------------------------------------------------------------------
def cfg_sig(cfg):
    """Everything besides the gate / frequency points that changes the signal: an air reference is only valid for the same ones."""
    return (cfg["adc_sel"], cfg["dac"], cfg["pset"], cfg["outen"], cfg["khz10"], cfg["noecho"], cfg["ne_shift"], cfg["width_ns"],
            cfg["edge"], "fast" if (cfg["mode"] == MODE_LIVE or cfg["short_term"]) else "full")


def describe_points(mode, pts):
    f0, n0 = pts[0]
    f1, n1 = pts[-1]
    if BG_KIND[mode] == "live" or len(pts) == 1:
        return f"{f0:g} MHz at gate step {n0}"
    if BG_KIND[mode] == "freq":
        return f"{f0:g} ... {f1:g} MHz at gate step {n0}"
    return f"gate steps {n0} ... {n1} at {f0:g} MHz"


def bg_check(bg, cfg):
    """(ok, reason): is the stored air reference usable for the run described by cfg?"""
    kind = BG_KIND[cfg["mode"]]
    if bg is None or bg.get("kind") != kind:
        return False, {"live": "There is no air reference for live imaging yet.",
                       "snh": "There is no air sweep for sample and hold yet.",
                       "freq": "There is no air frequency sweep yet."}[kind]
    if bg["sig"] != cfg_sig(cfg):
        return False, ("The settings changed since the air reference was captured "
                       "(ADC, DAC, VCO power, pulse width, no-echo or terminal count).")
    if any(pkey(*p) not in bg["e"] for p in cfg["points"]):
        return False, (f"The air reference covers {describe_points(cfg['mode'], bg['points'])}, "
                       f"this run needs {describe_points(cfg['mode'], cfg['points'])}.")
    return True, ""


# ---------------------------------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------------------------------
class Writer(threading.Thread):
    """Writes frame files in the background so that acquisition never waits for the disk."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue(maxsize=3000)
        self.err = None
        self.count = 0
        self.start()

    def put(self, path, payload, mtime):
        self.q.put((path, payload, mtime))

    def run(self):
        while True:
            it = self.q.get()
            if it is None:
                self.q.task_done()
                return
            path, payload, mtime = it
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if isinstance(payload, tuple):                 # ("f4", array)
                    payload = np.ascontiguousarray(payload[1], dtype="<f4").tobytes()
                with open(path, "wb") as f:
                    f.write(payload)
                os.utime(path, (mtime, mtime))
                self.count += 1
            except Exception as e:
                self.err = e
            self.q.task_done()

    def close(self):
        self.q.put(None)
        self.join()


class ImageSaver(threading.Thread):
    """Renders the displayed image of every frame and writes PNG (as shown) and / or TIFF (32-bit float numbers)."""

    def __init__(self, png, tiff):
        super().__init__(daemon=True)
        self.q = queue.Queue(maxsize=300)
        self.png, self.tiff = png, tiff
        self.err = None
        self.count = 0
        self.start()

    def put(self, folder, name, b, disp, ts, sub):
        self.q.put((folder, name, b, disp, ts, sub))

    def run(self):
        while True:
            it = self.q.get()
            if it is None:
                self.q.task_done()
                return
            folder, name, b, disp, ts, sub = it
            try:
                img, unit, note = quantity_image(b, disp["qkey"])
                if self.tiff:
                    p = os.path.join(folder, "tiff", name + ".tif")
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    Image.fromarray(np.ascontiguousarray(img, dtype=np.float32)).save(p, format="TIFF")
                    os.utime(p, (ts, ts))
                if self.png:
                    lo, hi = limits(img, disp)
                    im = render_image(img, lo, hi, disp["cmap"], IMG_W, IMG_H, disp["qname"] + (("   [" + unit + "]") if unit else ""),
                                      sub + (("    [" + note + "]") if note else ""), disp["rot"], disp["flipx"], disp["flipy"], img_opts(disp))
                    p = os.path.join(folder, "png", name + ".png")
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    im.save(p)
                    os.utime(p, (ts, ts))
                self.count += 1
            except Exception as e:
                self.err = e
            self.q.task_done()

    def close(self):
        self.q.put(None)
        self.join()


def make_video(png_dir, out_path, fps, log):
    """Compile frame_*.png of a folder into a video.  Tries OpenCV, then imageio, then the ffmpeg program."""
    files = sorted(f for f in os.listdir(png_dir) if f.startswith("frame_") and f.endswith(".png"))
    if len(files) < 2:
        log(f"Video: only {len(files)} image(s) in {png_dir} - no video made.")
        return False
    first = Image.open(os.path.join(png_dir, files[0]))
    w, h = first.size
    w -= w % 2
    h -= h % 2
    try:
        import cv2
        vw = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        if not vw.isOpened():
            raise RuntimeError("cannot open the video file")
        for fn in files:
            im = np.asarray(Image.open(os.path.join(png_dir, fn)).convert("RGB"))[:h, :w, ::-1]
            vw.write(np.ascontiguousarray(im))
        vw.release()
        return True
    except ImportError:
        pass
    except Exception as e:
        log("Video (OpenCV) failed: " + str(e))
    try:
        import imageio.v2 as iio
        wr = iio.get_writer(out_path, fps=fps, codec="libx264", macro_block_size=2)
        for fn in files:
            wr.append_data(np.asarray(Image.open(os.path.join(png_dir, fn)).convert("RGB"))[:h, :w])
        wr.close()
        return True
    except ImportError:
        pass
    except Exception as e:
        log("Video (imageio) failed: " + str(e))
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if ff:
        import tempfile
        lst = os.path.join(tempfile.mkdtemp(), "list.txt")
        with open(lst, "w") as f:
            for fn in files:
                f.write("file '%s'\nduration %.6f\n" % (os.path.join(png_dir, fn).replace("'", "'\\''"), 1.0 / fps))
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", f"crop={w}:{h}:0:0,format=yuv420p",
                            "-r", str(fps), out_path], capture_output=True, text=True)
        if r.returncode == 0:
            return True
        log("Video (ffmpeg) failed: " + r.stderr.strip()[:300])
        return False
    log("Video: no encoder found. Install one of:  pip install opencv-python   or   pip install imageio imageio-ffmpeg   (or the ffmpeg program).")
    return False


class RunOut:
    """One time-stamped experiment folder; with bursts every burst is a set_NN sub folder of its own."""

    def __init__(self, cfg, log):
        root = cfg["save_root"]
        os.makedirs(root, exist_ok=True)
        base = time.strftime("%Y-%m-%d %H-%M-%S") + "_" + auto_tag(cfg) + (("_" + sanitize(cfg["tag"])) if cfg["tag"].strip() else "")
        d, k = os.path.join(root, base), 2
        while os.path.exists(d):
            d = os.path.join(root, f"{base}_{k}")
            k += 1
        os.makedirs(d)
        self.dir = d
        self.base = d
        self.set_no = 0
        self.cfg = cfg
        self.log = log
        self.w = Writer()
        self.imgs = ImageSaver(cfg["save_png"], cfg["save_tiff"]) if (cfg["save_png"] or cfg["save_tiff"]) else None
        self.csv = open(os.path.join(d, "sweep.csv"), "w", buffering=1)
        self.csv.write("phase,kind,index,set,pass,frequency_MHz,gate_step,gate_time_after_TX_close_ns,time_after_TX_open_ns,"
                       "term_count,time_unix,time_iso\n")
        self.nframes = 0
        log("Run folder: " + d)

    def new_set(self, k, bg, bursts):
        """Start a data set (a burst) and put a copy of the air reference into it."""
        self.set_no = k
        self.base = os.path.join(self.dir, "set_%02d" % k) if bursts else self.dir
        os.makedirs(self.base, exist_ok=True)
        if bg is not None:
            self.save_air(bg)

    def _vid(self, phase, kind, n):
        sub = "echo" if kind == "echo" else "no-echo"
        pre = "echo" if kind == "echo" else "noecho"
        top = "" if phase == "sample" else "air-sweep"
        return [os.path.join(self.base, top, sub, f"{pre}_{ch}_{n}_o.dat") for ch in "IQ"]

    def save(self, phase, kind, idx, pass_no, I, Q, ts, f, n, tc):
        cfg = self.cfg
        if cfg["save_dat"]:
            pi, pq = self._vid(phase, kind, idx + 1)
            self.w.put(pi, ("f4", I), ts)
            self.w.put(pq, ("f4", Q), ts)
        self.csv.write(f"{phase},{kind},{idx + 1},{self.set_no},{pass_no},{f},{n},{time_closed_ns(n)},{time_open_ns(cfg, n)},{tc},"
                       f"{ts:.4f},{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}\n")
        self.nframes += 1

    def save_air(self, bg):
        """Live imaging: air-echo-I.dat ... in the folder.  Sweeps: air-sweep/echo/... one file per point, in run order."""
        if not self.cfg["save_dat"]:
            return
        pts = self.cfg["points"]
        if self.cfg["mode"] == MODE_LIVE:
            key = pkey(*pts[0])
            for kind, k in (("echo", "e"), ("noecho", "ne")):
                if key not in bg[k]:
                    continue
                I, Q = bg[k][key]
                pre = "air-echo" if kind == "echo" else "air-noecho"
                self.w.put(os.path.join(self.base, f"{pre}-I.dat"), ("f4", I), bg["t"][key])
                self.w.put(os.path.join(self.base, f"{pre}-Q.dat"), ("f4", Q), bg["t"][key])
        else:
            for j, (f, n) in enumerate(pts):
                key = pkey(f, n)
                for kind, k in (("echo", "e"), ("noecho", "ne")):
                    if key in bg[k]:
                        I, Q = bg[k][key]
                        pi, pq = self._vid("air", kind, j + 1)
                        self.w.put(pi, ("f4", I), bg["t"][key])
                        self.w.put(pq, ("f4", Q), bg["t"][key])

    def image(self, name, b, disp, ts, sub):
        if self.imgs is not None:
            self.imgs.put(os.path.join(self.base, "images"), name, b, disp, ts, sub)

    def write_settings(self, extra=None):
        with open(os.path.join(self.dir, "settings.txt"), "w") as f:
            f.write(settings_text(self.cfg, extra))

    def close(self, extra=None):
        self.w.close()
        if self.imgs is not None:
            self.imgs.close()
        self.csv.close()
        self.write_settings(extra)
        if self.w.err:
            self.log("WARNING: a file could not be written: " + str(self.w.err))
        if self.imgs is not None and self.imgs.err:
            self.log("WARNING: an image could not be written: " + str(self.imgs.err))


def settings_text(cfg, extra=None):
    p = cfg["points"]
    t0 = timing_for(cfg, p[0][1], "echo")
    m = cfg["mode"]
    steps = sorted({n for _, n in p})
    freqs = sorted({f for f, _ in p})
    out = ["date M/D/Y and time H/M/S = " + time.strftime("%m/%d/%Y %H:%M:%S"),
           "Mode: " + LABEL_OF[m].split("  (")[0],
           "Bit File Name: " + cfg["bit_file"] + ("   (simulated)" if cfg["sim"] else ""),
           "Frequency: " + (f"{freqs[0]} MHz" if len(freqs) == 1 else f"{freqs[0]} ... {freqs[-1]} MHz, {len(freqs)} points"),
           "OUTEN: " + str(cfg["outen"]), "PSET: " + str(cfg["pset"]), "10 kHz frequency resolution: " + ("yes" if cfg["khz10"] else "no"),
           "Transmit pulse width (ns): %d   (TX registers %d ... %d)" % (cfg["width_ns"], TX_START_STEP, tx_end_step(cfg)),
           "Term Count (first point): " + str(t0["term"]),
           "TX_SWITCH_EN Settings: " + str(t0["tx"]), "PULSE_AND Settings: " + str(t0["pa"]),
           "RX_SWITCH_EN Settings: " + str(t0["rx"]) + "   (opens when TX closes; end moves with the gate)",
           "GLOB_EN Settings: " + str(t0["ge"]) + "   (start moves with the gate)",
           "LO_CTRL Settings: " + str(t0["lo"]),
           "ADC_CAP Settings: " + str(t0["adc"]) + "   (moves with the gate)",
           "DAC Voltage for All Pixels: " + str(cfg["dac"]),
           "ADC Used: " + str(cfg["adc_sel"]) + "  (0 = gain of 5, 1 = no gain)",
           "Gate step (%d ns each, 0 = TX closes and RX opens): " % NS_PER_STEP
           + (str(steps[0]) if len(steps) == 1 else f"{steps[0]} ... {steps[-1]}, {len(steps)} points"),
           "Time of a gate step: step x %d ns after TX closes" % NS_PER_STEP,
           "No-echo: " + (f"yes, gate shifted +{cfg['ne_shift']} steps" if cfg["noecho"] else "no"),
           "Rolling average (frames, images only): " + str(cfg["roll"]) + "   (the .dat files hold every single frame)",
           "Air reference frames per point: " + str(cfg["air_n"]),
           "Delay after each gate / frequency change (ms): %g" % cfg["delay_ms"],
           "Frame interval (s): %g" % cfg["interval_s"], "Pause between sweeps (s): %g" % cfg["pass_gap_s"],
           "Burst (s): %g   rest (s): %g" % (cfg["burst_s"], cfg["rest_s"]),
           "Stop after (s): %g" % cfg["max_run_s"], "RF switched off when done: " + ("yes" if cfg["rf_off"] else "no"),
           "Video from the PNG images: " + (f"yes, {VIDEO_FPS} frames/s" if cfg.get("video") else "no")]
    if cfg["integrate"]:
        out.append("Integrated image over gate steps: %d ... %d" % (cfg["int_from"], cfg["int_to"]))
    out += ["Pixel pitch (um): 50", "File format: float32 little-endian volts, 128 x 128, no header (I and Q in separate files)"]
    for k, v in (extra or {}).items():
        out.append(f"{k}: {v}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------------------------------
# the acquisition job (runs in a worker thread, never touches Tk)
# ---------------------------------------------------------------------------------------------------------------------
class Job(threading.Thread):
    def __init__(self, app, kind, cfg):
        super().__init__(daemon=True)
        self.app = app
        self.kind = kind                                       # connect | air | run
        self.cfg = cfg
        self.q = app.q
        self.cancel = app.cancel
        self.be = None
        self.opened = False
        self.stats = {}
        self.out = None
        self.t_end = None
        self.last_t = None
        self.next_t = None
        self.tm = {}

    def log(self, m):
        self.q.put(("log", m))

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()
        if self.t_end is not None and time.time() > self.t_end:
            raise TimeUp()

    def wait(self, seconds, label=None):
        end = time.time() + seconds
        last = 0.0
        while True:
            self.check()
            now = time.time()
            left = end - now
            if left <= 0:
                return
            if label and seconds >= 1.5 and now - last >= 0.5:
                self.q.put(("status", f"{label}: {left:.0f} s left"))
                last = now
            time.sleep(min(left, 0.05))

    # ---- thread body
    def run(self):
        info = {}
        try:
            info = getattr(self, "do_" + self.kind)() or {}
        except TimeUp:
            info = dict(self.stats, timeup=True)
            self.log("Time limit (%g s) reached - the run ended by itself." % self.cfg["max_run_s"])
        except Cancelled:
            info = dict(self.stats, cancelled=True)
            self.log("Stopped.")
        except Exception as e:
            info = {"error": str(e)}
            self.log("ERROR: " + str(e))
            if not isinstance(e, (RuntimeError, ValueError)):
                self.log(traceback.format_exc())
        finally:
            self.rf_off()
            if self.out is not None:
                status = ("stopped" if info.get("cancelled") else "time limit reached" if info.get("timeup")
                          else "ended with an error" if "error" in info else "finished")
                try:
                    self.out.close({"status": status, "frames saved": self.stats.get("saved", 0), "sets": self.stats.get("sets", 0)})
                    info.setdefault("dir", self.out.dir)
                    if self.cfg.get("video"):
                        self.make_videos(self.out.dir)
                except Exception as e:
                    self.log("could not finish the run folder: " + str(e))
                self.out = None
            if self.opened and self.be is not None:
                try:
                    self.be.end()
                except Exception:
                    pass
        self.q.put(("done", self.kind, info))

    def make_videos(self, run_dir):
        """One video per data set (burst), made from its PNG images."""
        dirs = [run_dir] + [os.path.join(run_dir, d) for d in sorted(os.listdir(run_dir)) if d.startswith("set_")]
        for d in dirs:
            pd = os.path.join(d, "images", "png")
            if os.path.isdir(pd):
                self.q.put(("status", "Making the video ..."))
                out = os.path.join(d, "video.mp4")
                if make_video(pd, out, VIDEO_FPS, self.log):
                    self.log("Video saved: " + out)

    def rf_off(self):
        if not (self.opened and self.be is not None and self.cfg["rf_off"] and self.kind != "connect"):
            return
        try:
            self.be.rf_off()
            self.log("RF output switched off.")
        except Exception as e:
            self.log("WARNING: could not switch the RF output off (" + str(e) + ") - check the imager.")

    # ---- device
    def connect(self):
        cfg, app = self.cfg, self.app
        be = app.be
        want = ("sim",) if cfg["sim"] else (cfg["bit_file"], cfg["driver_dir"] or os.path.dirname(os.path.abspath(__file__)))
        if be is not None and (be.sim != cfg["sim"] or be.key != want):
            be.disconnect()
            be = None
        if be is None:
            be = SimBackend() if cfg["sim"] else RealBackend()
            be.connect(cfg, self.log, self.cancel)
            app.be = be
            self.q.put(("connected", "Simulated imager" if cfg["sim"] else "Connected"))
        self.be = be
        return be

    def kinds(self):
        return ["echo", "noecho"] if self.cfg["noecho"] else ["echo"]

    def prepare(self):
        be = self.connect()
        be.begin()
        self.opened = True
        if be.dac_v is None or abs(be.dac_v - self.cfg["dac"]) > 1e-9:
            be.load_dac(self.cfg["dac"], self.log, self.cancel)
        self.tm = {(n, k): timing_for(self.cfg, n, k) for _, n in self.cfg["points"] for k in self.kinds()}
        if be.set_vco(self.cfg["points"][0][0], self.cfg):
            self.wait(max(VCO_SETTLE_S, self.cfg["delay_ms"] / 1000.0))
        if self.cfg["max_run_s"] > 0:
            self.t_end = time.time() + self.cfg["max_run_s"]
        self.last_t = None
        return be

    def set_freq(self, f):
        """Program the VCO (only when the frequency changes) and wait the safety delay."""
        if self.be.set_vco(f, self.cfg):
            self.wait(self.cfg["delay_ms"] / 1000.0)

    def apply_timing(self, t):
        """Change the timing registers and wait the safety delay before anything is read."""
        if t == self.last_t:
            return
        self.be.set_timing(t)
        self.last_t = t
        self.wait(self.cfg["delay_ms"] / 1000.0)

    def grab_avg(self, n, dummy=False):
        be, adc = self.be, self.cfg["adc_sel"]
        if dummy:
            be.grab(adc)
        sI = sQ = None
        for _ in range(n):
            self.check()
            I, Q = bytes_to_iq(be.grab(adc))
            if sI is None:
                sI, sQ = I.astype(np.float32), Q.astype(np.float32)
            else:
                sI += I
                sQ += Q
        ts = time.time()
        if n > 1:
            sI /= n
            sQ /= n
        return sI, sQ, ts

    def shoot(self, n, kind, count=1, dummy=False):
        self.apply_timing(self.tm[(n, kind)])
        return self.grab_avg(count, dummy)

    def pace(self):
        """Frame interval: one frame (or sweep point) every x s, measured start to start."""
        iv = self.cfg["interval_s"]
        if iv <= 0:
            return
        now = time.time()
        due = self.next_t if self.next_t is not None else now
        if due > now:
            self.wait(due - now, "Waiting for the next frame")
        self.next_t = max(due + iv, time.time())

    def meta(self, f, n, idx, total, pass_no, label, frame_no):
        cfg = self.cfg
        pts = cfg["points"]
        m = dict(idx=idx, total=total, pass_no=pass_no, f=f, n=n, width_ns=cfg["width_ns"], label=label, trace_id=("run",))
        if cfg["mode"] == MODE_LIVE:
            m.update(x=frame_no, xlabel="frame", live=True, pass_no=1)
        elif cfg["mode"] == MODE_FREQ:
            m.update(x=f, xlabel="frequency (MHz)", xr=(pts[0][0], pts[-1][0]))
        else:
            m.update(x=time_closed_ns(n), xlabel=TIME_XLABEL, xr=(time_closed_ns(pts[0][1]), time_closed_ns(pts[-1][1])))
        return m

    # ---- jobs
    def do_connect(self):
        self.connect()
        return {}

    def do_air(self):
        """Air reference (no sample on the transducer) for the current mode: echo and no-echo at every point of the run."""
        cfg = self.cfg
        pts, kinds = cfg["points"], self.kinds()
        be = self.prepare()
        be.hint(sample=False)
        nfr = cfg["air_n"]
        self.log(f"Capturing the air reference: {describe_points(cfg['mode'], pts)}, {len(pts)} point{'s' if len(pts) > 1 else ''}, "
                 f"{nfr} frame{'s' if nfr > 1 else ''} each ...")
        bg = dict(kind=BG_KIND[cfg["mode"]], sig=cfg_sig(cfg), e={}, ne={}, t={}, points=list(pts), nfr=nfr, stamp=time.time())
        for idx, (f, n) in enumerate(pts):
            self.check()
            self.set_freq(f)
            key = pkey(f, n)
            for kind in kinds:
                I, Q, ts = self.shoot(n, kind, nfr, dummy=(len(pts) == 1))
                bg["e" if kind == "echo" else "ne"][key] = (I, Q)
                bg["t"][key] = ts
            e, ne = bg["e"][key], bg["ne"].get(key)
            b = dict(self.meta(f, n, idx, len(pts) if len(pts) > 1 else 0, 1, "air reference", idx),
                     i=e[0], q=e[1], ni=ne[0] if ne else None, nq=ne[1] if ne else None, ref_e=None)
            b["trace_id"] = ("air",)
            self.q.put(("frame", b))
        self.q.put(("bg", bg["kind"], bg))
        self.log("Air reference captured.")
        return {"air": True, "frames": len(pts)}

    def get_bg(self):
        cfg = self.cfg
        bg = self.app.bgs.get(BG_KIND[cfg["mode"]])
        ok, why = bg_check(bg, cfg)
        if ok:
            return bg
        if cfg["mode"] != MODE_LIVE:
            raise ValueError(why + " Capture the air sweep first (without the sample).")
        self.log(("WARNING: " + why + " " if bg is not None else "No air reference yet. ") + "Showing raw values - capture air to see echo - air.")
        return None

    def rest(self, secs):
        """Rest between bursts.  Long rests switch RF off and close the imager (when 'RF off' is ticked)."""
        cfg = self.cfg
        if secs <= 0:
            return
        release = cfg["rf_off"] and secs >= RF_RELEASE_MIN_S
        if release:
            self.rf_off()
            self.be.end()
            self.opened = False
            self.log(f"Resting {secs:g} s - RF off and imager released.")
        else:
            self.log(f"Resting {secs:g} s.")
        self.wait(secs, "Resting until the next set")
        if release:
            self.be.begin()
            self.opened = True
            self.be.set_vco(cfg["points"][0][0], cfg)
            self.wait(max(VCO_SETTLE_S, cfg["delay_ms"] / 1000.0))
            self.last_t = None

    def do_run(self):
        cfg = self.cfg
        pts, kinds = cfg["points"], self.kinds()
        live = cfg["mode"] == MODE_LIVE
        repeat = cfg["repeat"]
        bursts = cfg["burst_s"] > 0 and repeat
        be = self.prepare()
        be.hint(sample=True)
        bg = self.get_bg()
        roll = Roll(cfg["roll"])
        frames = saved = pass_no = set_no = 0
        raws = {}
        hist = collections.deque(maxlen=40)
        t_start = time.time()
        what = describe_points(cfg["mode"], pts)
        self.log({MODE_LIVE: "Live imaging: ", MODE_SNH: "Sample & hold sweep: ", MODE_CONT: "Continuous sample & hold: ",
                  MODE_FREQ: "Frequency sweep: "}[cfg["mode"]] + what
                 + (f" ({len(pts)} points)" if len(pts) > 1 else "") + (", repeating until Stop" if (repeat and not live) else "")
                 + f"; delay after each change {cfg['delay_ms']:g} ms" + ("; air subtracted" if bg else ""))
        out = None
        if cfg["record"]:
            out = self.out = RunOut(cfg, self.log)
            out.write_settings({"status": "recording"})
            self.q.put(("saving", out.dir))
        disp_of = self.app.get_disp
        while True:                                                                    # one iteration = one data set (burst)
            self.check()                                                               # time limit / Stop: no empty set folder
            set_no += 1
            in_set = 0
            set_open = False                                                           # the set folder is made with its first frame
            burst_end = time.time() + cfg["burst_s"] if bursts else None
            self.next_t = None
            while True:                                                                # one iteration = one pass over the points
                pass_no += 1
                if not live:
                    roll.clear()
                    raws = {}
                for idx, (f, n) in enumerate(pts):
                    self.check()
                    self.pace()
                    self.set_freq(f)
                    res = {k: self.shoot(n, k) for k in kinds}
                    e, ne = res["echo"], res.get("noecho")
                    ref = bg["e"][pkey(f, n)] if bg else None
                    refn = bg["ne"].get(pkey(f, n)) if bg else None
                    hist.append(e[2])
                    rate = (len(hist) - 1) / (hist[-1] - hist[0]) if len(hist) > 1 and hist[-1] > hist[0] else 0.0
                    ps = 1 if live else pass_no
                    rb = dict(self.meta(f, n, idx, 0 if live else len(pts), ps, "live" if live else "sample", frames),
                              i=e[0], q=e[1], ni=ne[0] if ne else None, nq=ne[1] if ne else None, ref_e=ref, ref_n=refn, rate=rate)
                    raws[idx] = rb
                    roll.push((e[0], e[1], ne[0] if ne else None, ne[1] if ne else None, ref[0] if ref else None, ref[1] if ref else None,
                               refn[0] if refn else None, refn[1] if refn else None))
                    m = roll.mean()
                    b = dict(rb, i=m[0], q=m[1], ni=m[2], nq=m[3], ref_e=(m[4], m[5]) if m[4] is not None else None,
                             ref_n=(m[6], m[7]) if m[6] is not None else None, roll_n=roll.n, roll_have=len(roll.win), trace_b=rb, set_no=set_no, sets=set_no if bursts else 0)
                    if out is not None:
                        if not set_open:
                            out.new_set(set_no, bg, bursts)
                            set_open = True
                        for k in kinds:
                            out.save("sample", k, in_set, ps, res[k][0], res[k][1], res[k][2], f, n, self.tm[(n, k)]["term"])
                        in_set += 1
                        saved += 1
                        out.image("frame_%05d" % in_set, b, disp_of(), e[2], sub_text(b))
                    frames += 1
                    b["saved"] = saved if out is not None else None
                    self.stats = {"frames": frames, "passes": pass_no, "saved": saved, "fps": rate, "sets": set_no}
                    if self.q.qsize() < Q_QUEUE_MAX:
                        self.q.put(("frame", b))
                    if live and burst_end is not None and time.time() >= burst_end:
                        break
                if not repeat:
                    break
                if burst_end is not None and time.time() >= burst_end:
                    break
                if not live and cfg["pass_gap_s"] > 0:
                    self.wait(cfg["pass_gap_s"], "Pause between sweeps")
                    self.next_t = None
                    if burst_end is not None and time.time() >= burst_end:
                        break
            if not bursts:
                break
            self.rest(cfg["rest_s"])
        # single sweep: the image integrated over the chosen gate steps
        if cfg["integrate"] and cfg["mode"] == MODE_SNH and out is not None:
            a, c = cfg["int_from"], cfg["int_to"]
            sel = [r for r in raws.values() if a <= r["n"] <= c]
            if sel:
                ib = integrate_bundles(sel)
                ib.update(label=f"integrated gate steps {a} ... {c}  ({time_closed_ns(a)} ... {time_closed_ns(c)} ns after TX closes)",
                          f=cfg["points"][0][0], roll_n=1, roll_have=1)
                out.image(f"integrated_steps_{a}-{c}", ib, disp_of(), time.time(), sub_text(ib))
        dur = time.time() - t_start
        return {"frames": frames, "passes": pass_no, "saved": saved, "fps": frames / dur if dur > 0 else 0, "seconds": round(dur, 1),
                "sets": set_no, "finished": True}


# ---------------------------------------------------------------------------------------------------------------------
# 3D view of a gate sweep: the gate steps become depth
# ---------------------------------------------------------------------------------------------------------------------
class Viz3D(ttk.Frame):
    """Orthogonal views (XY, XZ, YZ) of the frames of one sample-and-hold sweep stacked along the gate time.
    Depth = (gate step - start step) x 5 ns x speed of sound / 2   (the echo travels down and back, so half the path)."""

    def __init__(self, parent, app, bg):
        super().__init__(parent)
        self.app = app
        v = app.v
        self.stack = None                                       # (nz, 128, 128) float32, oriented like the 2D map
        self.steps = []
        self.depth = np.zeros(0)
        self.dz_um = 0.0
        self.pos = [0, 64, 64]                                  # z, y, x
        self.lo, self.hi = 0.0, 1.0
        self._job = None
        self._photo = None
        self._tiles = None
        self._busy = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        ttk.Label(self, text="3D view", font=bold).grid(row=0, column=0, sticky="w")
        c = ttk.Frame(self)
        c.grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(c, text="Start step").grid(row=0, column=0)
        ttk.Entry(c, textvariable=v["v3_start"], width=5).grid(row=0, column=1, padx=(3, 8))
        ttk.Label(c, text="Stop step").grid(row=0, column=2)
        ttk.Entry(c, textvariable=v["v3_stop"], width=5).grid(row=0, column=3, padx=(3, 8))
        ttk.Label(c, text="Pitch (um)").grid(row=0, column=4)
        ttk.Entry(c, textvariable=v["v3_pitch"], width=5).grid(row=0, column=5, padx=(3, 0))
        c2 = ttk.Frame(self)
        c2.grid(row=2, column=0, sticky="w", pady=(3, 0))
        ttk.Label(c2, text="Material").grid(row=0, column=0)
        cb = ttk.Combobox(c2, textvariable=v["v3_mat"], state="readonly", width=11, values=[m[0] for m in ECHO_MATERIALS] + [ECHO_CUSTOM])
        cb.grid(row=0, column=1, padx=(3, 6))
        cb.bind("<<ComboboxSelected>>", self._material)
        ttk.Label(c2, text="c (m/s)").grid(row=0, column=2)
        ttk.Entry(c2, textvariable=v["v3_c"], width=6).grid(row=0, column=3, padx=(3, 8))
        ttk.Button(c2, text="Update", width=7, command=self.refresh).grid(row=0, column=4)
        ttk.Button(c2, text="Napari", width=7, command=self.open_napari).grid(row=0, column=5, padx=(4, 0))
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.cv.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        self.cv.bind("<Configure>", lambda e: self.render())
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<B1-Motion>", self._click)
        self.zs = ttk.Scale(self, from_=0, to=1, command=self._zscale)
        self.zs.grid(row=4, column=0, sticky="ew", pady=(3, 0))
        self.info = ttk.Label(self, text="", foreground="#555", wraplength=380, justify="left")
        self.info.grid(row=5, column=0, sticky="w")
        self.readout = ttk.Label(self, text="", foreground="#333")
        self.readout.grid(row=6, column=0, sticky="w")
        for k in ("v3_start", "v3_stop", "v3_c"):
            v[k].trace_add("write", lambda *a: self.schedule())

    # ---- data
    def _material(self, _e=None):
        m = echo_material(self.app.v["v3_mat"].get())
        if m is not None:
            self.app.v["v3_c"].set("%g" % m[2])

    def schedule(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(250, self.refresh)

    def refresh(self):
        self._job = None
        app, v = self.app, self.app.v
        try:
            a, b = int(float(v["v3_start"].get())), int(float(v["v3_stop"].get()))
            c = float(v["v3_c"].get())
            if c <= 0:
                raise ValueError
        except ValueError:
            self.stack = None
            self.info.configure(text="Enter start step, stop step and the speed of sound.")
            self.render()
            return
        src = app.sweep_source()
        steps = sorted(n for n in src if a <= n <= b)
        if b <= a or not steps:
            self.stack = None
            self.info.configure(text="Stop must be above start." if b <= a else
                                "Run a sample and hold sweep (or a continuous one) that covers these steps.")
            self.render()
            return
        key = QDICT[v["quantity"].get()]
        rot, fx, fy = int(v["rot"].get() or 0), bool(v["flipx"].get()), bool(v["flipy"].get())
        self.stack = np.stack([orient(quantity_image(src[n], key)[0], rot, fx, fy) for n in steps]).astype(np.float32)
        self.steps = steps
        self.dz_um = NS_PER_STEP * 1e-9 * c / 2.0 * 1e6
        self.depth = (np.asarray(steps, dtype=float) - a) * self.dz_um
        nz = len(steps)
        self.pos[0] = max(0, min(self.pos[0], nz - 1))
        self.zs.configure(to=max(nz - 1, 1))
        self._set_slider(self.pos[0])
        self.lo, self.hi = limits(self.stack, app.disp)
        self.info.configure(text=f"{nz} gate steps ({steps[0]} to {steps[-1]}), depth 0 to {self.depth[-1]:.0f} um, "
                                 f"{self.dz_um:.1f} um per step;  colours {self.lo:.3g} to {self.hi:.3g}")
        self.render()

    def _set_slider(self, z):
        self._busy = True
        try:
            self.zs.set(z)
        finally:
            self._busy = False

    def _zscale(self, val):
        if self._busy or self.stack is None:
            return
        self.pos[0] = max(0, min(int(round(float(val))), len(self.steps) - 1))
        self.render()

    # ---- drawing
    def render(self):
        cv = self.cv
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 80 or H < 80:
            return
        im = Image.new("RGB", (W, H), "white")
        dr = ImageDraw.Draw(im)
        self._tiles = None
        if self.stack is None:
            dr.text((W // 2, H // 2), "no sweep data yet", fill="#888888", font=font(13), anchor="mm")
            self._show(im)
            return
        nz, ny, nx = self.stack.shape
        z, y, x = self.pos
        gap = 6
        zt = int(max(44, min(130, 0.30 * min(W, H))))
        s = max(60, min(W - zt - gap, H - zt - gap - 2))
        rng = (self.hi - self.lo) or 1.0
        table = lut(self.app.v["cmap"].get())

        def colour(a):
            return Image.fromarray(table[(np.clip((a - self.lo) / rng, 0, 1) * 255).astype(np.uint8)])
        im.paste(colour(self.stack[z]).resize((s, s), Image.NEAREST), (0, 0))
        im.paste(colour(self.stack[:, y, :]).resize((s, zt), Image.NEAREST), (0, s + gap))
        im.paste(colour(self.stack[:, :, x].T).resize((zt, s), Image.NEAREST), (s + gap, 0))
        cx, cy = (x + 0.5) / nx * s, (y + 0.5) / ny * s
        cz = (z + 0.5) / nz * zt
        cc = "#00e5ff"
        dr.line([cx, 0, cx, s], fill=cc)
        dr.line([0, cy, s, cy], fill=cc)
        dr.line([cx, s + gap, cx, s + gap + zt], fill=cc)
        dr.line([0, s + gap + cz, s, s + gap + cz], fill=cc)
        dr.line([s + gap, cy, s + gap + zt, cy], fill=cc)
        dr.line([s + gap + cz, 0, s + gap + cz, s], fill=cc)
        for box, name in (((0, 0, s, s), "XY"), ((0, s + gap, s, s + gap + zt), "XZ"), ((s + gap, 0, s + gap + zt, s), "YZ")):
            dr.rectangle(box, outline="#999999")
            dr.text((box[0] + 4, box[1] + 3), name, fill="white", font=font(13), stroke_width=2, stroke_fill="black")
        dr.text((s + gap + zt / 2, s + gap + 2), "depth", fill="#555555", font=font(12), anchor="mt")
        dr.text((s + gap + zt / 2, s + gap + 16), f"{self.depth[z]:.0f} um", fill="black", font=font(14), anchor="mt")
        bar = np.linspace(0, 255, zt).astype(np.uint8)[None, :].repeat(10, axis=0)
        im.paste(Image.fromarray(table[bar]), (s + gap, s + gap + 36))
        self._tiles = (s, gap, zt, nz, ny, nx)
        self._show(im)
        self.readout.configure(text=f"x {x}   y {y}   step {self.steps[z]}   depth {self.depth[z]:.0f} um   value {self.stack[z, y, x]:.4g}")

    def _show(self, im):
        self._photo = ImageTk.PhotoImage(im)
        self.cv.delete("all")
        self.cv.create_image(0, 0, image=self._photo, anchor="nw")

    def _click(self, e):
        if self._tiles is None or self.stack is None:
            return
        s, gap, zt, nz, ny, nx = self._tiles
        z, y, x = self.pos
        if e.x < s and e.y < s:
            x, y = int(e.x / s * nx), int(e.y / s * ny)
        elif e.x < s and e.y >= s + gap:
            x, z = int(e.x / s * nx), int((e.y - s - gap) / zt * nz)
        elif e.x >= s + gap and e.y < s:
            y, z = int(e.y / s * ny), int((e.x - s - gap) / zt * nz)
        else:
            return
        self.pos = [max(0, min(z, nz - 1)), max(0, min(y, ny - 1)), max(0, min(x, nx - 1))]
        self._set_slider(self.pos[0])
        self.render()

    # ---- napari
    def napari_command(self):
        """Saves the stack and returns the command line that opens it in napari (in a separate process)."""
        import tempfile
        d = tempfile.mkdtemp(prefix="meg2_stack_")
        path = os.path.join(d, "stack.npy")
        np.save(path, self.stack)
        try:
            pitch = float(self.app.v["v3_pitch"].get())
        except ValueError:
            pitch = PIXEL_PITCH_UM
        cm = self.app.v["cmap"].get()
        cm = cm if cm in ("inferno", "magma", "viridis", "plasma", "gray", "hot") else "viridis"
        code = ("import sys, numpy as np, napari\n"
                "a = np.load(sys.argv[1])\n"
                "v = napari.Viewer(ndisplay=3)\n"
                "v.add_image(a, name='gate sweep', scale=(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[3])), colormap=sys.argv[4],\n"
                "            contrast_limits=(float(sys.argv[5]), float(sys.argv[6])))\n"
                "v.axes.visible = True\n"
                "napari.run()\n")
        return [sys.executable, "-c", code, path, "%g" % self.dz_um, "%g" % pitch, cm, "%g" % self.lo, "%g" % self.hi]

    def open_napari(self):
        if self.stack is None:
            messagebox.showinfo("3D view", "There is no stack yet. Run a sample and hold sweep first.")
            return
        import importlib.util
        if importlib.util.find_spec("napari") is None:
            messagebox.showinfo("napari", "napari is not installed.\n\nIn a terminal:\n    pip install \"napari[all]\"\n\n"
                                          "then press this button again.")
            return
        import subprocess
        try:
            subprocess.Popen(self.napari_command())
        except Exception as e:
            messagebox.showwarning("napari", "Could not start napari: " + str(e))
# ---------------------------------------------------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------------------------------------------------
class App:
    PREF_KEYS = ["sim", "driver_dir", "bit_file", "adc", "dac", "pset", "mode", "freq", "f_from", "f_to", "f_step", "width",
                 "step_live", "step_start", "step_end", "repeat", "noecho", "roll", "air_live", "air_sweep", "delay", "max_run",
                 "rf_off", "interval", "pass_gap", "burst", "rest", "save_root", "tag", "save_dat", "save_png", "save_tiff",
                 "quantity", "tq", "metric", "cmap", "scale", "vmin", "vmax", "plo", "phi", "rot", "flipx", "flipy",
                 "int_from", "int_to", "khz10", "outen", "ne_shift", "edge", "short_term", "video", "show_axes", "show_title", "show_desc",
                 "fsize", "region", "r0", "r1", "c0", "c1", "v3_start", "v3_stop", "v3_mat", "v3_c", "v3_pitch"]

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.be = None
        self.bgs = {"live": None, "snh": None, "freq": None}         # most recent air reference of each kind
        self.job = None
        self.latest = None
        self.run_cfg = None
        self.run_t0 = 0.0
        self.confirm = lambda title, msg: messagebox.askyesno(title, msg)
        self.disp = {}
        self.master_win = None
        self.master_widgets = []
        self._int_cache = None
        self._reset_trace()
        self.locked = []
        self._img_photo = None
        self._tr_photo = None
        self.run_dir = ""
        root.title("MEG2 sample-and-hold acquisition")
        root.geometry(f"{max(1240, min(1560, root.winfo_screenwidth() - 30))}x{max(620, min(940, root.winfo_screenheight() - 90))}")
        root.minsize(1240, 620)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._vars()
        self._build()
        self._load_prefs()
        self._disp_sync()
        self._mode_changed()
        root.after(40, self._poll)
        self._redraw()

    # ---- variables
    def _vars(self):
        S, B = tk.StringVar, tk.BooleanVar
        self.v = dict(sim=B(value=SIMULATE), driver_dir=S(value=DRIVER_DIR), bit_file=S(value=BIT_FILE), adc=S(value=ADC_CHOICES[0]),
                      dac=S(value="2.8"), pset=S(value=PSET_CHOICES[3]), mode=S(value=MODE_LABELS[0][0]), freq=S(value="1853.0"),
                      f_from=S(value=FSWEEP_DEFAULT[0]), f_to=S(value=FSWEEP_DEFAULT[1]), f_step=S(value=FSWEEP_DEFAULT[2]),
                      width=S(value=str(PULSE_DEFAULT_NS)), step_live=S(value=str(FIRST_ECHO_STEP)), step_start=S(value="0"),
                      step_end=S(value=str(STEP_MAX)), repeat=B(value=True), noecho=B(value=True), roll=S(value="1"),
                      air_live=S(value=str(AIR_FRAMES_LIVE)), air_sweep=S(value=str(AIR_FRAMES_SWEEP)),
                      delay=S(value="%g" % DEFAULT_DELAY_MS), max_run=S(value="%g" % MAX_RUN_S_DEFAULT), rf_off=B(value=RF_OFF_WHEN_DONE),
                      interval=S(value="0"), pass_gap=S(value="0"), burst=S(value="0"), rest=S(value="100"),
                      save_root=S(value=SAVE_ROOT), tag=S(value=""), record=B(value=False), save_dat=B(value=True),
                      save_png=B(value=True), save_tiff=B(value=False),
                      quantity=S(value=QUANTITIES[0][0]), tq=S(value=TRACE_QUANTITIES[0][0]), metric=S(value=METRICS[0]),
                      cmap=S(value="inferno"), scale=S(value=SCALES[0]), vmin=S(value="-0.3"), vmax=S(value="0.3"),
                      plo=S(value=str(PLO)), phi=S(value=str(PHI)), rot=S(value="180"), flipx=B(value=False), flipy=B(value=False),
                      show_int=B(value=False), int_from=S(value="10"), int_to=S(value="15"),
                      khz10=B(value=False), outen=B(value=True), ne_shift=S(value=str(NOECHO_SHIFT)), edge=S(value=str(PULSE_EDGE_STEPS)),
                      short_term=B(value=SHORT_TERM), video=B(value=False), show_axes=B(value=True), show_title=B(value=True),
                      show_desc=B(value=True), fsize=S(value="14"), region=S(value=REGIONS[0]), r0=S(value="64"), r1=S(value="70"),
                      c0=S(value="64"), c1=S(value="70"), v3_start=S(value="18"), v3_stop=S(value="42"), v3_mat=S(value="Silicon"),
                      v3_c=S(value="%g" % C_SILICON_MS), v3_pitch=S(value="%g" % PIXEL_PITCH_UM))

    # ---- layout
    def _build(self):
        v, root = self.v, self.root
        nb = ttk.Notebook(root)
        nb.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        page = ttk.Frame(nb)
        nb.add(page, text="Acquire")
        self.nb = nb
        self.echo = EchoTab(nb, v)
        nb.add(self.echo, text="Pulse and echo simulator")
        holder = ttk.Frame(page)
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
        right = ttk.Frame(page, padding=(6, 8, 10, 8))
        right.grid(row=0, column=1, sticky="nsew")
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        def add(w):
            self.locked.append(w)
            return w

        def E(parent, key, width=8):
            return add(ttk.Entry(parent, textvariable=v[key], width=width))

        def frame(title, row, pady=6):
            f = ttk.LabelFrame(left, text=title, padding=8)
            f.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else pady, 0))
            return f

        def line(f, row, pady=5):
            r = ttk.Frame(f)
            r.grid(row=row, column=0, sticky="w", pady=(0 if row == 0 else pady, 0))
            return r

        # -- imager -----------------------------------------------------------------------------------
        f = frame("Imager", 0)
        f.columnconfigure(1, weight=1)
        add(ttk.Checkbutton(f, text="Simulate (no hardware)", variable=v["sim"])).grid(row=0, column=0, columnspan=2, sticky="w")
        self.conn_lbl = ttk.Label(f, text="not connected", foreground="#a33")
        self.conn_lbl.grid(row=0, column=2, sticky="e")
        ttk.Label(f, text="Driver folder").grid(row=1, column=0, sticky="w", pady=(4, 0))
        E(f, "driver_dir", 30).grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        add(ttk.Button(f, text="...", width=3, command=lambda: self._browse_dir("driver_dir"))).grid(row=1, column=2, pady=(4, 0))
        ttk.Label(f, text="Bit file").grid(row=2, column=0, sticky="w", pady=(3, 0))
        E(f, "bit_file", 30).grid(row=2, column=1, sticky="ew", padx=4, pady=(3, 0))
        add(ttk.Button(f, text="...", width=3, command=self._browse_bit)).grid(row=2, column=2, pady=(3, 0))
        r = ttk.Frame(f)
        r.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Label(r, text="DAC (V)").grid(row=0, column=0)
        E(r, "dac", 6).grid(row=0, column=1, padx=(3, 10))
        ttk.Label(r, text="ADC").grid(row=0, column=2)
        add(ttk.Combobox(r, textvariable=v["adc"], state="readonly", values=ADC_CHOICES, width=14)).grid(row=0, column=3, padx=(3, 10))
        ttk.Label(r, text="VCO power").grid(row=0, column=4)
        add(ttk.Combobox(r, textvariable=v["pset"], state="readonly", values=PSET_CHOICES, width=11)).grid(row=0, column=5, padx=(3, 0))
        r = ttk.Frame(f)
        r.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.btn_conn = tk.Button(r, text="Connect", command=self.on_connect, bg="#2e9e44", fg="white", activebackground="#27863a",
                                  activeforeground="white", disabledforeground="#d8e8dc", relief="raised", bd=2, padx=16, pady=2)
        self.btn_conn.grid(row=0, column=0)
        self.btn_master = ttk.Button(r, text="Master settings ...", command=self.open_master)
        self.btn_master.grid(row=0, column=1, padx=(8, 0))

        # -- mode --------------------------------------------------------------------------------------
        f = frame("Mode", 1)
        cb = add(ttk.Combobox(f, textvariable=v["mode"], state="readonly", values=[m[0] for m in MODE_LABELS], width=46))
        cb.grid(row=0, column=0, sticky="ew")
        cb.bind("<<ComboboxSelected>>", lambda e: self._mode_changed())

        # -- frequency ---------------------------------------------------------------------------------
        f = frame("Frequency (VCO)", 2)
        r = line(f, 0)
        ttk.Label(r, text="Frequency (MHz)").grid(row=0, column=0)
        self.e_freq = E(r, "freq", 9)
        self.e_freq.grid(row=0, column=1, padx=(4, 0))
        r = line(f, 1)
        ttk.Label(r, text="Sweep from").grid(row=0, column=0)
        self.e_f0 = E(r, "f_from", 8)
        self.e_f0.grid(row=0, column=1, padx=(4, 6))
        ttk.Label(r, text="to").grid(row=0, column=2)
        self.e_f1 = E(r, "f_to", 8)
        self.e_f1.grid(row=0, column=3, padx=(4, 6))
        ttk.Label(r, text="step").grid(row=0, column=4)
        self.e_fs = E(r, "f_step", 6)
        self.e_fs.grid(row=0, column=5, padx=(4, 4))
        ttk.Label(r, text="MHz").grid(row=0, column=6)
        self.ck_repeat = add(ttk.Checkbutton(f, text="Repeat the frequency sweep until Stop", variable=v["repeat"], command=self._mode_changed))
        self.ck_repeat.grid(row=2, column=0, sticky="w", pady=(5, 0))

        # -- gate --------------------------------------------------------------------------------------
        f = frame("Gate (sampling) time  -  step 0 = TX closes and RX opens, 5 ns per step", 3)
        r = line(f, 0)
        ttk.Label(r, text="Transmit pulse width (ns)").grid(row=0, column=0)
        self.e_width = E(r, "width", 6)
        self.e_width.grid(row=0, column=1, padx=(4, 0))
        r = line(f, 1)
        ttk.Label(r, text="Gate step").grid(row=0, column=0)
        self.e_g = E(r, "step_live", 6)
        self.e_g.grid(row=0, column=1, padx=(4, 0))
        r = line(f, 2)
        ttk.Label(r, text="Sweep gate step from").grid(row=0, column=0)
        self.e_g0 = E(r, "step_start", 6)
        self.e_g0.grid(row=0, column=1, padx=(4, 6))
        ttk.Label(r, text="to").grid(row=0, column=2)
        self.e_g1 = E(r, "step_end", 6)
        self.e_g1.grid(row=0, column=3, padx=(4, 6))
        ttk.Label(r, text="maximum %d = %d ns" % (STEP_MAX, STEP_MAX * NS_PER_STEP), foreground="#555").grid(row=0, column=4)
        self.sum_lbl = ttk.Label(f, text="", foreground="#555", wraplength=430, justify="left")
        self.sum_lbl.grid(row=3, column=0, sticky="w", pady=(5, 0))

        # -- averaging / air ---------------------------------------------------------------------------
        f = frame("Averaging and air reference", 4)
        r = line(f, 0)
        ttk.Label(r, text="Frames averaged per image").grid(row=0, column=0)
        E(r, "roll", 5).grid(row=0, column=1, padx=(4, 14))
        add(ttk.Checkbutton(r, text="Also acquire no-echo", variable=v["noecho"])).grid(row=0, column=2)
        r = line(f, 1)
        ttk.Label(r, text="Air reference frames").grid(row=0, column=0)
        self.e_air = add(ttk.Entry(r, textvariable=v["air_live"], width=5))
        self.e_air.grid(row=0, column=1, padx=(4, 0))

        # -- timing of the acquisition ---------------------------------------------------------------
        f = frame("Timing", 5)
        r = line(f, 0)
        ttk.Label(r, text="Acquire a frame every").grid(row=0, column=0)
        self.e_int = E(r, "interval", 7)
        self.e_int.grid(row=0, column=1, padx=(4, 4))
        ttk.Label(r, text="s   0 = as fast as possible").grid(row=0, column=2)
        r = line(f, 1)
        ttk.Label(r, text="Pause between sweeps").grid(row=0, column=0)
        self.e_gap = E(r, "pass_gap", 7)
        self.e_gap.grid(row=0, column=1, padx=(4, 4))
        ttk.Label(r, text="s").grid(row=0, column=2)
        r = line(f, 2)
        ttk.Label(r, text="Burst: acquire for").grid(row=0, column=0)
        self.e_burst = E(r, "burst", 7)
        self.e_burst.grid(row=0, column=1, padx=(4, 4))
        ttk.Label(r, text="s, then rest for").grid(row=0, column=2)
        self.e_rest = E(r, "rest", 7)
        self.e_rest.grid(row=0, column=3, padx=(4, 4))
        ttk.Label(r, text="s    0 = no bursts").grid(row=0, column=4)
        self.tim_lbl = ttk.Label(f, text="", foreground="#555", wraplength=430, justify="left")
        self.tim_lbl.grid(row=3, column=0, sticky="w", pady=(5, 0))

        # -- recording --------------------------------------------------------------------------------
        f = frame("Recording", 6)
        f.columnconfigure(1, weight=1)
        add(ttk.Checkbutton(f, text="Record", variable=v["record"])).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Save folder").grid(row=1, column=0, sticky="w", pady=(4, 0))
        E(f, "save_root", 30).grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        add(ttk.Button(f, text="...", width=3, command=lambda: self._browse_dir("save_root"))).grid(row=1, column=2, pady=(4, 0))
        ttk.Label(f, text="Name").grid(row=2, column=0, sticky="w", pady=(3, 0))
        E(f, "tag", 30).grid(row=2, column=1, sticky="ew", padx=4, pady=(3, 0))
        r = ttk.Frame(f)
        r.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        add(ttk.Checkbutton(r, text=".dat files for the video maker", variable=v["save_dat"])).grid(row=0, column=0, columnspan=2, sticky="w")
        add(ttk.Checkbutton(r, text="PNG images", variable=v["save_png"])).grid(row=1, column=0, sticky="w")
        add(ttk.Checkbutton(r, text="TIFF images", variable=v["save_tiff"])).grid(row=1, column=1, sticky="w", padx=(14, 0))
        add(ttk.Checkbutton(r, text="Generate video (from the PNG images)", variable=v["video"])).grid(row=2, column=0, columnspan=2, sticky="w")
        v["repeat"].trace_add("write", lambda *a: self._mode_changed())
        for k in ("freq", "f_from", "f_to", "f_step", "width", "step_live", "step_start", "step_end", "delay", "roll", "interval", "pass_gap",
                  "burst", "rest", "max_run", "int_from", "int_to", "khz10", "ne_shift", "edge"):
            v[k].trace_add("write", lambda *a: self._summary())

        # -- right side ----------------------------------------------------------------------------
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        top = ttk.Frame(right)
        top.grid(row=0, column=0, sticky="ew")
        self.btn_air = ttk.Button(top, text="Capture air", command=self.on_air)
        self.btn_air.grid(row=0, column=0)
        self.btn_start = ttk.Button(top, text="Start", command=self.on_start)
        self.btn_start.grid(row=0, column=1, padx=(6, 0))
        self.btn_stop = ttk.Button(top, text="Stop", command=self.on_stop, state="disabled")
        self.btn_stop.grid(row=0, column=2, padx=(6, 12))
        self.air_lbl = ttk.Label(top, text="", foreground="#555")
        self.air_lbl.grid(row=1, column=0, columnspan=4, sticky="w", pady=(3, 0))
        viz = ttk.Frame(right)
        viz.grid(row=1, column=0, sticky="nsew", pady=(6, 4))
        viz.columnconfigure(0, weight=1)
        viz.columnconfigure(1, weight=1)
        viz.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viz, bg=bg, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.viz3 = Viz3D(viz, self, bg)
        self.viz3.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        dsp = ttk.Frame(right)
        dsp.grid(row=2, column=0, sticky="ew")
        ttk.Label(dsp, text="Show").grid(row=0, column=0)
        cq = ttk.Combobox(dsp, textvariable=v["quantity"], state="readonly", values=[q[0] for q in QUANTITIES], width=30)
        cq.grid(row=0, column=1, padx=(3, 8))
        cq.bind("<<ComboboxSelected>>", lambda e: self._quantity_changed())
        ttk.Label(dsp, text="colormap").grid(row=0, column=2)
        cc = ttk.Combobox(dsp, textvariable=v["cmap"], state="readonly", values=CMAPS, width=9)
        cc.grid(row=0, column=3, padx=(3, 8))
        cc.bind("<<ComboboxSelected>>", lambda e: self._display_changed())
        ttk.Label(dsp, text="rotate").grid(row=0, column=4)
        cr = ttk.Combobox(dsp, textvariable=v["rot"], state="readonly", values=["0", "90", "180", "270"], width=4)
        cr.grid(row=0, column=5, padx=(3, 8))
        cr.bind("<<ComboboxSelected>>", lambda e: self._display_changed())
        ttk.Checkbutton(dsp, text="flip L-R", variable=v["flipx"], command=self._display_changed).grid(row=0, column=6)
        ttk.Checkbutton(dsp, text="flip U-D", variable=v["flipy"], command=self._display_changed).grid(row=0, column=7, padx=(6, 0))
        d2 = ttk.Frame(right)
        d2.grid(row=3, column=0, sticky="ew", pady=(3, 0))
        ttk.Label(d2, text="Scale").grid(row=0, column=0)
        cs = ttk.Combobox(d2, textvariable=v["scale"], state="readonly", values=SCALES, width=22)
        cs.grid(row=0, column=1, padx=(3, 10))
        cs.bind("<<ComboboxSelected>>", lambda e: self._display_changed())
        for c, (lbl, key, w) in enumerate((("percentiles", "plo", 4), ("-", "phi", 4), ("min", "vmin", 7), ("max", "vmax", 7))):
            ttk.Label(d2, text=lbl).grid(row=0, column=2 + 2 * c, padx=(0 if c == 0 else 6, 2))
            ttk.Entry(d2, textvariable=v[key], width=w).grid(row=0, column=3 + 2 * c)
            v[key].trace_add("write", lambda *a: self._display_changed())
        dps = ttk.Frame(right)
        dps.grid(row=4, column=0, sticky="ew", pady=(3, 0))
        ttk.Label(dps, text="Plot settings").grid(row=0, column=0, padx=(0, 10))
        for c, (txt, key) in enumerate((("axes (rows and columns)", "show_axes"), ("title", "show_title"), ("description", "show_desc"))):
            ttk.Checkbutton(dps, text=txt, variable=v[key], command=self._display_changed).grid(row=0, column=1 + c, padx=(0, 10))
        ttk.Label(dps, text="font size").grid(row=0, column=4)
        ttk.Spinbox(dps, from_=8, to=30, width=4, textvariable=v["fsize"], command=self._display_changed).grid(row=0, column=5, padx=(4, 0))
        v["fsize"].trace_add("write", lambda *a: self._display_changed())
        d3 = ttk.Frame(right)
        d3.grid(row=5, column=0, sticky="ew", pady=(3, 0))
        self.ck_int = ttk.Checkbutton(d3, text="Integrated image of gate steps", variable=v["show_int"], command=self._display_changed)
        self.ck_int.grid(row=0, column=0)
        self.e_i0 = ttk.Entry(d3, textvariable=v["int_from"], width=5)
        self.e_i0.grid(row=0, column=1, padx=(6, 4))
        ttk.Label(d3, text="to").grid(row=0, column=2)
        self.e_i1 = ttk.Entry(d3, textvariable=v["int_to"], width=5)
        self.e_i1.grid(row=0, column=3, padx=(4, 8))
        ttk.Label(d3, text="mean of those gates; single sweeps also save it", foreground="#555").grid(row=0, column=4)
        for k in ("int_from", "int_to"):
            v[k].trace_add("write", lambda *a: self._display_changed())
        tc = ttk.Frame(right)
        tc.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(tc, text="Trace of").grid(row=0, column=0)
        ct = ttk.Combobox(tc, textvariable=v["tq"], state="readonly", values=[q[0] for q in TRACE_QUANTITIES], width=24)
        ct.grid(row=0, column=1, padx=(4, 6))
        ct.bind("<<ComboboxSelected>>", lambda e: self._recompute_trace())
        ttk.Label(tc, text="taken as").grid(row=0, column=2)
        cm = ttk.Combobox(tc, textvariable=v["metric"], state="readonly", values=METRICS, width=20)
        cm.grid(row=0, column=3, padx=(4, 8))
        cm.bind("<<ComboboxSelected>>", lambda e: self._recompute_trace())
        tc2 = ttk.Frame(right)
        tc2.grid(row=7, column=0, sticky="ew", pady=(3, 0))
        ttk.Label(tc2, text="over").grid(row=0, column=0)
        cg = ttk.Combobox(tc2, textvariable=v["region"], state="readonly", values=REGIONS, width=12)
        cg.grid(row=0, column=1, padx=(4, 10))
        cg.bind("<<ComboboxSelected>>", lambda e: self._region_changed())
        self.reg_entries = []
        for c, (lbl, key) in enumerate((("row", "r0"), ("to", "r1"), ("column", "c0"), ("to", "c1"))):
            ttk.Label(tc2, text=lbl).grid(row=0, column=2 + 2 * c, padx=(8 if lbl != "to" else 4, 3))
            e = ttk.Entry(tc2, textvariable=v[key], width=5)
            e.grid(row=0, column=3 + 2 * c)
            self.reg_entries.append(e)
            v[key].trace_add("write", lambda *a: self._sched_region())
        self.trace_canvas = tk.Canvas(right, bg=bg, highlightthickness=0, height=140)
        self.trace_canvas.grid(row=8, column=0, sticky="ew", pady=(2, 0))
        self.trace_canvas.bind("<Configure>", lambda e: self._draw_trace())
        self.prog = ttk.Progressbar(right, mode="determinate", maximum=1000)
        self.prog.grid(row=9, column=0, sticky="ew", pady=(6, 0))
        self.status = ttk.Label(right, text="Ready.", anchor="w")
        self.status.grid(row=10, column=0, sticky="ew", pady=(2, 0))
        lf = ttk.Frame(right)
        lf.grid(row=11, column=0, sticky="ew", pady=(4, 0))
        lf.columnconfigure(0, weight=1)
        self.log_txt = tk.Text(lf, height=5, wrap="word", state="disabled", font=("TkFixedFont", 9))
        sb = ttk.Scrollbar(lf, command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=sb.set)
        self.log_txt.grid(row=0, column=0, sticky="ew")
        sb.grid(row=0, column=1, sticky="ns")
        self._region_state()

    # ---- master settings
    def open_master(self):
        if self.master_win is not None and self.master_win.winfo_exists():
            self.master_win.lift()
            return
        v = self.v
        w = tk.Toplevel(self.root)
        w.title("Master settings")
        w.transient(self.root)
        w.geometry("+%d+%d" % (self.root.winfo_rootx() + 90, self.root.winfo_rooty() + 70))
        self.master_win = w
        f = ttk.Frame(w, padding=14)
        f.grid(row=0, column=0)
        self.master_widgets = []

        def add(x):
            self.master_widgets.append(x)
            return x
        sf = ttk.LabelFrame(f, text="Safety", padding=8)
        sf.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(sf, text="Delay after each gate / frequency change (ms)").grid(row=0, column=0, sticky="w")
        self.e_delay = add(ttk.Entry(sf, textvariable=v["delay"], width=7))
        self.e_delay.grid(row=0, column=1, padx=6)
        ttk.Label(sf, text="minimum %g ms" % MIN_DELAY_FLOOR_MS, foreground="#555").grid(row=0, column=2, sticky="w")
        ttk.Label(sf, text="Stop after (s)").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.e_max = add(ttk.Entry(sf, textvariable=v["max_run"], width=7))
        self.e_max.grid(row=1, column=1, padx=6, pady=(5, 0))
        add(ttk.Checkbutton(sf, text="Turn RF off when done", variable=v["rf_off"])).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        add(ttk.Checkbutton(f, text="10 kHz frequency resolution", variable=v["khz10"])).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Off (original script): the VCO frequency is rounded to 0.1 MHz.   On: to 0.01 MHz.", foreground="#555",
                  wraplength=420, justify="left").grid(row=2, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(0, 8))
        add(ttk.Checkbutton(f, text="VCO output enabled (OUTEN)", variable=v["outen"])).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(f, text="No-echo gate shift (steps)").grid(row=4, column=0, sticky="w")
        add(ttk.Entry(f, textvariable=v["ne_shift"], width=6)).grid(row=4, column=1, sticky="w", padx=6)
        ttk.Label(f, text="TX register steps beyond the pulse width").grid(row=5, column=0, sticky="w", pady=(6, 0))
        add(ttk.Entry(f, textvariable=v["edge"], width=6)).grid(row=5, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(f, text="The original TX registers 20 ... 42 span 22 steps for the 100 ns pulse, so 2.", foreground="#555",
                  wraplength=420, justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))
        add(ttk.Checkbutton(f, text="Sweeps use the short terminal count of live imaging", variable=v["short_term"])).grid(
            row=7, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Off (original script): terminal count 1023, one frame takes much longer.", foreground="#555",
                  wraplength=420, justify="left").grid(row=8, column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(0, 10))
        ttk.Button(f, text="Close", command=w.destroy).grid(row=9, column=0, sticky="w")
        self._master_state()

    def _master_state(self, running=None):
        on = not (self.job is not None and self.job.is_alive()) if running is None else not running
        for x in self.master_widgets:
            try:
                _state(x, on)
            except tk.TclError:
                pass

    # ---- small helpers
    def _log(self, m):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", time.strftime("%H:%M:%S  ") + m + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def _browse_dir(self, key):
        d = filedialog.askdirectory(initialdir=self.v[key].get() or os.path.expanduser("~"))
        if d:
            self.v[key].set(d)

    def _browse_bit(self):
        p = filedialog.askopenfilename(filetypes=[("Bit files", "*.bit"), ("All files", "*.*")])
        if p:
            self.v["bit_file"].set(p)

    def _mode(self):
        return MODE_OF.get(self.v["mode"].get(), MODE_LIVE)

    def _mode_changed(self):
        m = self._mode()
        st = _state
        st(self.e_freq, m != MODE_FREQ)
        for e in (self.e_f0, self.e_f1, self.e_fs):
            st(e, m == MODE_FREQ)
        st(self.ck_repeat, m == MODE_FREQ)
        st(self.e_g, m in (MODE_LIVE, MODE_FREQ))
        for e in (self.e_g0, self.e_g1):
            st(e, m in (MODE_SNH, MODE_CONT))
        repeat = m in (MODE_LIVE, MODE_CONT) or (m == MODE_FREQ and self.v["repeat"].get())
        st(self.e_gap, m in (MODE_CONT, MODE_FREQ) and repeat)
        for e in (self.e_burst, self.e_rest):
            st(e, repeat)
        self.e_air.configure(textvariable=self.v["air_live"] if m == MODE_LIVE else self.v["air_sweep"])
        self.btn_air.configure(text="Capture air" if m == MODE_LIVE else "Capture air sweep")
        self.btn_start.configure(text={MODE_LIVE: "Start live imaging", MODE_SNH: "Start sweep", MODE_CONT: "Start continuous sweep",
                                       MODE_FREQ: "Start frequency sweep"}[m])
        self.ck_int.configure(state="normal" if m in (MODE_SNH, MODE_CONT) else "disabled")
        for e in (self.e_i0, self.e_i1):
            e.configure(state="normal" if m in (MODE_SNH, MODE_CONT) else "disabled")
        self._summary()

    def _summary(self):
        try:
            cfg = self.collect(quiet=True)
        except Exception as e:
            self.sum_lbl.configure(text=str(e), foreground="#a33")
            self.tim_lbl.configure(text="")
            self._air_status(None)
            return
        p = cfg["points"]
        w = cfg["width_ns"]
        n0, n1 = p[0][1], p[-1][1]
        if cfg["mode"] in (MODE_LIVE, MODE_FREQ):
            txt = f"Gate step {n0} = {time_closed_ns(n0)} ns after TX closes."
            if cfg["mode"] == MODE_FREQ:
                txt += f"  {len(p)} frequencies, {p[0][0]:g} ... {p[-1][0]:g} MHz."
        else:
            txt = f"{len(p)} gate steps, {time_closed_ns(n0)} ... {time_closed_ns(n1)} ns after TX closes."
        self.sum_lbl.configure(text=txt, foreground="#555")
        t = []
        if cfg["interval_s"] > 0:
            t.append(f"One frame every {cfg['interval_s']:g} s.")
        if cfg["burst_s"] > 0 and cfg["repeat"]:
            cyc = cfg["burst_s"] + cfg["rest_s"]
            t.append(f"Burst {cfg['burst_s']:g} s, rest {cfg['rest_s']:g} s: a new set every {cyc:g} s")
            if cfg["max_run_s"] > 0:
                t[-1] += f", {int(np.ceil(cfg['max_run_s'] / cyc - 1e-9))} sets within {cfg['max_run_s']:g} s."
            else:
                t[-1] += "."
        self.tim_lbl.configure(text=" ".join(t))
        self._air_status(cfg)

    def _air_status(self, cfg):
        if cfg is None:
            self.air_lbl.configure(text="")
            return
        ok, why = bg_check(self.bgs.get(BG_KIND[cfg["mode"]]), cfg)
        bg = self.bgs.get(BG_KIND[cfg["mode"]])
        if ok:
            self.air_lbl.configure(text=f"air reference ready: {describe_points(cfg['mode'], bg['points'])}", foreground="#2a7a2a")
        else:
            self.air_lbl.configure(text=why, foreground="#a33" if cfg["mode"] != MODE_LIVE else "#555")

    def _quantity_changed(self):
        self._disp_sync()
        self._recompute_trace()
        self._redraw()
        self.viz3.schedule()

    def _display_changed(self):
        self._disp_sync()
        if self._region() is not None:                              # rotating or flipping moves the traced pixels
            self._recompute_trace()
        else:
            self._redraw()
        self.viz3.schedule()

    def _region(self):
        """None for the whole frame, else (r0, r1, c0, c1) in pixels of the displayed (rotated / flipped) image."""
        mode = self.v["region"].get()
        if mode == REGIONS[0]:
            return None
        try:
            r0, c0 = int(float(self.v["r0"].get())), int(float(self.v["c0"].get()))
            r1, c1 = (r0, c0) if mode == REGIONS[1] else (int(float(self.v["r1"].get())), int(float(self.v["c1"].get())))
        except ValueError:
            return None
        cl = lambda x: max(0, min(N - 1, x))
        return cl(min(r0, r1)), cl(max(r0, r1)), cl(min(c0, c1)), cl(max(c0, c1))

    def _region_state(self):
        mode = self.v["region"].get()
        on = [mode != REGIONS[0], mode == REGIONS[2], mode != REGIONS[0], mode == REGIONS[2]]
        for e, o in zip(self.reg_entries, on):
            e.configure(state="normal" if o else "disabled")

    def _region_changed(self):
        self._region_state()
        self._recompute_trace()

    def _sched_region(self):
        if getattr(self, "_reg_job", None) is not None:
            try:
                self.root.after_cancel(self._reg_job)
            except Exception:
                pass
        self._reg_job = self.root.after(300, lambda: (setattr(self, "_reg_job", None), self._recompute_trace()))

    def sweep_source(self):
        """{gate step: frame bundle} of the last complete sample and hold sweep (else the one that is running)."""
        mode = (self.run_cfg or {}).get("mode", self._mode())
        if mode not in (MODE_SNH, MODE_CONT):
            return {}
        src = self.tr_b
        if self.prev_b and self.tr_total and len(src) < self.tr_total:
            src = self.prev_b
        return {b["n"]: b for b in src.values()}

    def _disp_sync(self):
        """Plain-dict copy of the display settings, read by the image writer thread."""
        v = self.v
        d = dict(self.disp)
        try:
            d.update(qname=v["quantity"].get(), qkey=QDICT[v["quantity"].get()], cmap=v["cmap"].get(), rot=int(v["rot"].get() or 0),
                     fixed=v["scale"].get() == SCALES[1], flipx=bool(v["flipx"].get()), flipy=bool(v["flipy"].get()),
                     axes=bool(v["show_axes"].get()), title=bool(v["show_title"].get()), desc=bool(v["show_desc"].get()))
            try:
                d["fs"] = max(8, min(30, int(float(v["fsize"].get()))))
            except ValueError:
                d.setdefault("fs", 14)
            for k in ("plo", "phi", "vmin", "vmax"):
                try:
                    d[k] = float(v[k].get())
                except ValueError:
                    d.setdefault(k, 0.0)
        except (KeyError, ValueError, tk.TclError):
            pass
        self.disp = d

    def get_disp(self):
        return self.disp

    # ---- configuration -> dict
    def collect(self, quiet=False):
        v = self.v
        g = lambda k: v[k].get().strip()

        def num(k, name, cast=float, lo=None, hi=None):
            try:
                x = cast(float(g(k))) if cast is int else cast(g(k))
            except ValueError:
                raise ValueError(f"{name}: '{g(k)}' is not a number")
            if lo is not None and x < lo:
                raise ValueError(f"{name} must be at least {lo:g}")
            if hi is not None and x > hi:
                raise ValueError(f"{name} must be at most {hi:g}")
            return x
        mode = self._mode()
        khz10 = bool(v["khz10"].get())
        res, dig = (0.01, 2) if khz10 else (0.1, 1)
        cfg = dict(mode=mode, sim=bool(v["sim"].get()), driver_dir=g("driver_dir"), bit_file=g("bit_file") or BIT_FILE,
                   adc_sel=ADC_CHOICES.index(g("adc")), dac=num("dac", "DAC voltage", float, DAC_V_MIN, DAC_V_MAX),
                   outen=1 if v["outen"].get() else 0, pset=PSET_CHOICES.index(g("pset")), khz10=khz10,
                   ne_shift=num("ne_shift", "No-echo shift", int, 1, 900), edge=num("edge", "TX register steps", int, 0, 10),
                   short_term=bool(v["short_term"].get()), noecho=bool(v["noecho"].get()),
                   width_ns=num("width", "Pulse width", int, PULSE_MIN_NS, PULSE_MAX_NS),
                   roll=num("roll", "Frames averaged per image", int, 1, 200),
                   air_n=num("air_live" if mode == MODE_LIVE else "air_sweep", "Air reference frames", int, 1, 1000),
                   delay_ms=num("delay", "Delay after each gate / frequency change", float, MIN_DELAY_FLOOR_MS, 60000),
                   max_run_s=num("max_run", "Stop after", float, 0, 30 * 86400), rf_off=bool(v["rf_off"].get()),
                   interval_s=num("interval", "Frame interval", float, 0, 10 ** 7), pass_gap_s=num("pass_gap", "Pause between sweeps", float, 0, 10 ** 7),
                   burst_s=num("burst", "Burst time", float, 0, 10 ** 7), rest_s=num("rest", "Rest time", float, 0, 10 ** 7),
                   record=bool(v["record"].get()), save_dat=bool(v["save_dat"].get()), save_png=bool(v["save_png"].get()),
                   save_tiff=bool(v["save_tiff"].get()), save_root=g("save_root") or SAVE_ROOT, tag=g("tag"))
        if cfg["width_ns"] % NS_PER_STEP:
            raise ValueError(f"Pulse width must be a multiple of {NS_PER_STEP} ns")
        cfg["repeat"] = mode in (MODE_LIVE, MODE_CONT) or (mode == MODE_FREQ and bool(v["repeat"].get()))

        def freq(k, name):
            f = num(k, name, float, FREQ_MIN_MHZ, FREQ_MAX_MHZ)
            if abs(f / res - round(f / res)) > 1e-6:
                raise ValueError(f"{name}: the resolution is {res:g} MHz" + ("" if khz10 else " (10 kHz is in Master settings)"))
            return round(f, dig)
        if mode == MODE_FREQ:
            f1, f2 = freq("f_from", "Sweep start"), freq("f_to", "Sweep end")
            st = num("f_step", "Frequency step", float, res)
            if abs(st / res - round(st / res)) > 1e-6:
                raise ValueError(f"Frequency step must be a multiple of {res:g} MHz")
            if f2 <= f1:
                raise ValueError("Sweep end must be larger than the start")
            freqs = frange(f1, f2, st, dig)
            if len(freqs) > MAX_SWEEP_POINTS:
                raise ValueError(f"more than {MAX_SWEEP_POINTS} frequencies")
            n = num("step_live", "Gate step", int, STEP_MIN, STEP_MAX)
            cfg["points"] = [(f, n) for f in freqs]
        else:
            f = freq("freq", "Frequency")
            if mode == MODE_LIVE:
                cfg["points"] = [(f, num("step_live", "Gate step", int, STEP_MIN, STEP_MAX))]
            else:
                a, b = num("step_start", "Sweep start", int, STEP_MIN, STEP_MAX), num("step_end", "Sweep end", int, STEP_MIN, STEP_MAX)
                if b <= a:
                    raise ValueError("Sweep end must be larger than the start")
                cfg["points"] = [(f, n) for n in range(a, b + 1)]
        cfg["freq"] = cfg["points"][0][0]
        for n in sorted({n for _, n in cfg["points"]}):                 # every timing register must stay inside its limits
            for kind in (["echo", "noecho"] if cfg["noecho"] else ["echo"]):
                timing_for(cfg, n, kind)
        if not cfg["repeat"]:
            cfg["burst_s"] = 0.0
        cfg["integrate"] = bool(v["show_int"].get()) and mode in (MODE_SNH, MODE_CONT)
        cfg["int_from"] = cfg["int_to"] = 0
        if cfg["integrate"]:
            cfg["int_from"], cfg["int_to"] = num("int_from", "Integrate from", int), num("int_to", "Integrate to", int)
            lo, hi = cfg["points"][0][1], cfg["points"][-1][1]
            if not (lo <= cfg["int_from"] <= cfg["int_to"] <= hi):
                raise ValueError(f"Integrate: choose gate steps inside the sweep ({lo} ... {hi}), from <= to")
        cfg["video"] = bool(v["video"].get())
        if cfg["video"]:
            if not cfg["record"]:
                raise ValueError("Generate video needs Record to be ticked.")
            cfg["save_png"] = True                                      # the video is made from the PNG images
        if cfg["record"] and not (cfg["save_dat"] or cfg["save_png"] or cfg["save_tiff"]):
            raise ValueError("Record is ticked but no file type is: tick .dat, PNG or TIFF.")
        return cfg

    # ---- buttons
    def _set_running(self, on):
        for w in self.locked:
            try:
                _state(w, not on)
            except tk.TclError:
                pass
        self.btn_conn.configure(state="disabled" if on else "normal")
        self.btn_air.configure(state="disabled" if on else "normal")
        self.btn_start.configure(state="disabled" if on else "normal")
        self.btn_stop.configure(state="normal" if on else "disabled")
        self._master_state(on)
        if not on:
            self._mode_changed()

    def _start_job(self, kind):
        try:
            cfg = self.collect()
        except Exception as e:
            self._log("Check the settings: " + str(e))
            messagebox.showerror("Settings", str(e))
            return False
        if kind == "run" and cfg["mode"] != MODE_LIVE:
            ok, why = bg_check(self.bgs.get(BG_KIND[cfg["mode"]]), cfg)
            if not ok:
                self._log("Air reference needed: " + why)
                messagebox.showwarning("Air reference needed", why + "\n\nClick 'Capture air sweep' first (without the sample), then start again.")
                return False
            if not cfg["record"] and not self.confirm("Record is off", "Record is not ticked - this sweep will be shown but nothing "
                                                                         "will be saved.\n\nStart anyway?"):
                return False
        self.cancel.clear()
        self._reset_trace()
        self._disp_sync()
        self.run_cfg, self.run_t0 = cfg, time.time()
        self._set_running(True)
        self.prog["value"] = 0
        self.job = Job(self, kind, cfg)
        self.job.start()
        return True

    def on_connect(self):
        self._start_job("connect")

    def on_air(self):
        self._start_job("air")

    def on_start(self):
        self._start_job("run")

    def on_stop(self):
        self.cancel.set()
        self.status.configure(text="Stopping ...")

    def on_close(self):
        self.cancel.set()
        if self.job is not None and self.job.is_alive():
            self.job.join(timeout=5)
        try:
            if self.be is not None:
                self.be.disconnect()
        except Exception:
            pass
        self._save_prefs()
        self.root.destroy()

    # ---- queue
    def _poll(self):
        last = None
        try:
            while True:
                m = self.q.get_nowait()
                k = m[0]
                if k == "log":
                    self._log(m[1])
                elif k == "status":
                    self.status.configure(text=m[1])
                elif k == "frame":
                    self._add_trace(m[1])
                    last = m[1]
                elif k == "bg":
                    self.bgs[m[1]] = m[2]
                elif k == "connected":
                    self.conn_lbl.configure(text=m[1], foreground="#2a7a2a")
                elif k == "saving":
                    self.run_dir = m[1]
                elif k == "done":
                    if last is not None:                        # show the final frame first, then the end-of-job message
                        self.latest = last
                        self._redraw()
                        self._status_from(last)
                        last = None
                    self._done(m[1], m[2])
        except queue.Empty:
            pass
        if last is not None:
            self.latest = last
            self._redraw()
            self._status_from(last)
        self.root.after(40, self._poll)

    def _status_from(self, b):
        cfg = self.run_cfg or {}
        lim = cfg.get("max_run_s", 0)
        el = time.time() - self.run_t0
        tail = f"   {el:.0f} s" + (f" of {lim:g} s" if lim else "")
        if b.get("saved") is not None:
            tail = f"   saved {b['saved']}" + tail
        sets = f"set {b['set_no']}   " if b.get("sets") else ""
        t = f"gate step {b['n']} ({time_closed_ns(b['n'])} ns after TX closes)"
        if b.get("label") == "air reference":
            s = f"Air reference: point {b['idx'] + 1} of {b['total']}   {b['f']:g} MHz, {t}" if b.get("total") else "Air reference captured"
            if b.get("total"):
                self.prog["value"] = 1000.0 * (b["idx"] + 1) / b["total"]
        elif b.get("live"):
            s = f"Live: {sets}frame {b['x'] + 1}   {b.get('rate', 0):.1f} frames/s" + tail
        elif cfg.get("mode") == MODE_FREQ:
            s = (f"Frequency sweep, pass {b['pass_no']}:  {sets}{b['f']:g} MHz   point {b['idx'] + 1}/{b['total']}   "
                 f"{b.get('rate', 0):.1f} frames/s" + tail)
            self.prog["value"] = 1000.0 * (b["idx"] + 1) / b["total"]
        else:
            s = (f"Sweep, pass {b['pass_no']}:  {sets}{t}   point {b['idx'] + 1}/{b['total']}   "
                 f"{b.get('rate', 0):.1f} frames/s" + tail)
            self.prog["value"] = 1000.0 * (b["idx"] + 1) / b["total"]
        self.status.configure(text=s)

    def _done(self, kind, info):
        self._set_running(False)
        self.prog["value"] = 0
        if "error" in info:
            self.status.configure(text="Error - see the log.")
            if kind == "connect" or not self.be:
                self.conn_lbl.configure(text="not connected", foreground="#a33")
            return
        n = info.get("frames", 0)
        sets = f" in {info['sets']} sets" if info.get("sets", 0) > 1 else ""
        if info.get("timeup"):
            txt = f"Time limit reached - stopped after {n} frames{sets}."
        elif info.get("cancelled"):
            txt = f"Stopped after {n} frames{sets}."
        elif kind == "connect":
            txt = "Connected."
        elif kind == "air":
            txt = "Air reference captured. Place the sample and start."
        elif self._mode() == MODE_LIVE:
            txt = "Live imaging ended: %d frames, %.1f frames/s." % (n, info.get("fps", 0))
        else:
            txt = "Sweep finished: %d points in %.0f s." % (n, info.get("seconds", 0))
        if info.get("dir"):
            txt += "  Saved in: " + info["dir"]
            self._log("Saved in: " + info["dir"])
        self.status.configure(text=txt)
        self._summary()
        self.viz3.schedule()

    # ---- drawing
    def _reset_trace(self):
        self.tr_key = None
        self.tr_b = {}                 # idx -> frame bundle of the current pass (so the trace and the integral can be recomputed)
        self.prev_b = None             # the same for the last complete pass
        self.tr_total = 0
        self.tr_val = {}               # idx -> (x, value)
        self.tr_list = []              # (x, value) for live imaging (no sweep axis)
        self.tr_prev = None            # (xs, ys) of the previous pass
        self.tr_meta = dict(xlabel="", xr=None, unit="V", width=PULSE_DEFAULT_NS)
        self._int_cache = None

    def _trace_value(self, b):
        key = TQDICT[self.v["tq"].get()] or QDICT[self.v["quantity"].get()]
        img, unit, note = quantity_image(b, key)
        reg = self._region()
        if reg is not None:
            v = self.v
            img = orient(img, int(v["rot"].get() or 0), bool(v["flipx"].get()), bool(v["flipy"].get()))[reg[0]:reg[1] + 1, reg[2]:reg[3] + 1]
        return metric_value(img, self.v["metric"].get()), unit

    def _add_trace(self, b):
        b = b.get("trace_b", b)
        key = (b.get("trace_id"), b.get("pass_no"))
        if key != self.tr_key:
            if self.tr_key is not None and key[0] == self.tr_key[0] and key[1] is not None and self.tr_val:
                it = [self.tr_val[k] for k in sorted(self.tr_val)]
                self.tr_prev = ([p[0] for p in it], [p[1] for p in it])
                if self.tr_total and len(self.tr_b) == self.tr_total:
                    self.prev_b = self.tr_b
                    self.viz3.schedule()
            else:
                self.tr_prev = None
                if key[0] != (self.tr_key or (None,))[0]:
                    self.prev_b = None
            self.tr_key = key
            self.tr_b, self.tr_val, self.tr_list = {}, {}, []
        try:
            val, unit = self._trace_value(b)
        except Exception:
            return
        self.tr_meta.update(xlabel=b.get("xlabel", ""), xr=b.get("xr"), unit=unit, cur=b.get("x"), width=b.get("width_ns", PULSE_DEFAULT_NS))
        self.tr_total = b.get("total", 0)
        if not b.get("live") and 0 < b.get("total", 0) <= TRACE_CAP:
            self.tr_b[b["idx"]] = b
            self.tr_val[b["idx"]] = (b["x"], val)
        else:
            self.tr_list.append((b["x"], val))
            if len(self.tr_list) > 300:
                self.tr_list = self.tr_list[-300:]

    def _recompute_trace(self):
        self.tr_prev = None
        if self.tr_b:
            for i, b in self.tr_b.items():
                try:
                    self.tr_val[i] = (b["x"], self._trace_value(b)[0])
                except Exception:
                    pass
        else:
            self.tr_list = []
        self._draw_trace()
        self._redraw()

    def _trace_xy(self):
        if self.tr_val:
            it = [self.tr_val[k] for k in sorted(self.tr_val)]
        else:
            it = self.tr_list
        return [p[0] for p in it], [p[1] for p in it]

    def _integrated(self):
        """Mean of the frames of the chosen gate steps (sample - air at the same gates): last complete pass, else the running one."""
        try:
            a, c = int(float(self.v["int_from"].get())), int(float(self.v["int_to"].get()))
        except ValueError:
            return None
        src = self.tr_b
        if self.prev_b and self.tr_total and len(src) < self.tr_total:
            src = self.prev_b
        sel = [x for x in src.values() if a <= x["n"] <= c]
        if not sel:
            return None
        key = (id(src), len(src), a, c)
        if self._int_cache is not None and self._int_cache[0] == key:
            return self._int_cache[1]
        ib = integrate_bundles(sel)
        ib.update(label=f"integrated gate steps {a} ... {c}  ({time_closed_ns(a)} ... {time_closed_ns(c)} ns after TX closes)",
                  f=sel[0]["f"], roll_n=1, roll_have=1)
        self._int_cache = (key, ib)
        return ib

    def _redraw(self):
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        b = self.latest
        v = self.v
        rot = int(v["rot"].get() or 0)
        fx, fy = bool(v["flipx"].get()), bool(v["flipy"].get())
        if b is not None and v["show_int"].get() and self._mode() in (MODE_SNH, MODE_CONT):
            ib = self._integrated()
            if ib is not None:
                b = ib
        if b is None:
            im = render_image(None, 0, 1, v["cmap"].get(), W, H, "No image yet", "Capture air, then start.", rot, fx, fy, img_opts(self.disp))
        else:
            img, unit, note = quantity_image(b, QDICT[v["quantity"].get()])
            lo, hi = limits(img, self.disp)
            sub = sub_text(b) + (("    [" + note + "]") if note else "")
            o = img_opts(self.disp)
            o["roi"] = self._region()
            im = render_image(img, lo, hi, v["cmap"].get(), W, H, v["quantity"].get() + (("   [" + unit + "]") if unit else ""), sub,
                              rot, fx, fy, o)
        self._img_photo = ImageTk.PhotoImage(im)
        c.delete("all")
        c.create_image(0, 0, image=self._img_photo, anchor="nw")
        self._draw_trace()

    def _draw_trace(self):
        c = self.trace_canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50:
            return
        xs, ys = self._trace_xy()
        meta = self.tr_meta
        xl = meta["xlabel"]
        peak, marks = None, ()
        timeax, freqax = xl.startswith("time after"), xl.startswith("frequency")
        if timeax or freqax:
            px, py = xs, ys
            if self.tr_prev is not None and len(self.tr_prev[0]) > len(xs):       # a new pass has just started: use the last full one
                px, py = self.tr_prev
            if len(py) >= 3:
                dev = np.abs(np.asarray(py) - np.median(py))
                k = int(np.argmax(dev))
                if dev[k] > 0:
                    peak = (px[k], py[k], f"strongest change at {px[k]:.0f} ns  (gate step {int(round(px[k] / NS_PER_STEP))})" if timeax
                            else f"strongest change at {px[k]:.1f} MHz")
        ylab = (self.v["tq"].get().split("  ")[0] + " " + self.v["tq"].get().split("  ")[-1]).strip() if "  " in self.v["tq"].get() else self.v["tq"].get()
        im = render_trace(xs, ys, W, H, xl, ylab + ", " + self.v["metric"].get() + ((" [" + meta["unit"] + "]") if meta["unit"] else ""),
                          prev=self.tr_prev, xr=meta["xr"], marks=marks, cur=meta.get("cur") if self.tr_val else None, peak=peak)
        self._tr_photo = ImageTk.PhotoImage(im)
        c.delete("all")
        c.create_image(0, 0, image=self._tr_photo, anchor="nw")

    # ---- preferences
    def _load_prefs(self):
        try:
            with open(PREFS_FILE) as f:
                d = json.load(f)
        except Exception:
            return
        for k in self.PREF_KEYS:
            if k in d and k in self.v:
                try:
                    self.v[k].set(d[k])
                except Exception:
                    pass
        if self.v["mode"].get() not in MODE_OF:
            self.v["mode"].set(MODE_LABELS[0][0])
        self.v["record"].set(False)                                 # recording is always a deliberate choice
        if isinstance(d.get("echo"), dict):
            self.echo.set_state(d["echo"])

    def _save_prefs(self):
        try:
            with open(PREFS_FILE, "w") as f:
                d = {k: self.v[k].get() for k in self.PREF_KEYS if k in self.v}
                d["echo"] = self.echo.get_state()
                json.dump(d, f)
        except Exception:
            pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
