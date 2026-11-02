# MEG2 imager GUI

Tkinter GUI to acquire, display and record images from the Geegah MEG2 ultrasonic imager (XEM7305), and to simulate the
transmit pulse and the echoes of a layered chip.

![Acquire tab](docs/acquire_tab.png)

## Files

| File | What it is |
|---|---|
| `meg2_snh_acquire.py` | The GUI. Tab **Acquire** (live imaging, sample-and-hold sweep, continuous sweep, frequency sweep) and tab **Pulse and echo simulator**. |
| `meg2_video_gui.py` | Post-processing: turns a recorded run folder into a video or GIF. |
| `requirements.txt` | Python packages. |

Not in this repository (you need them to talk to the imager): `fpga.py`, `j_fp_vco.py`, `xem7305.bit`, and the Opal Kelly
FrontPanel software that `fpga.py` normally relies on. Put them next to `meg2_snh_acquire.py`, or enter their folder in

FrontPanelUSB-DriverOnly-5.3.6

**Driver folder**.

## Install

install FrontPanelUSB-DriverOnly-5.3.6 first. this is to communicate with OPAL KELLY interface for MEG2. 

Python 3.9 or newer (developed and tested on 3.12 / 3.13), with Tk.

```
pip install -r requirements.txt
```

Tk comes with the Windows and macOS installers from python.org. On Linux: `sudo apt install python3-tk python3-pil.imagetk`.

Optional: `opencv-python` or `imageio imageio-ffmpeg` (or the `ffmpeg` program) for **Generate video**;
`napari[all]` for the 3D **Napari** button.

## Run

```
python meg2_snh_acquire.py
```

No arguments. Tick **Simulate (no hardware)** to try everything without the imager.

With the imager: set Driver folder and Bit file, DAC / ADC / VCO power, press **Connect**, then **Capture air sweep**
(reference without the sample), then **Start sweep**.

## Quick guide

- **Time**: gate step 0 = TX closes = RX opens; 1 step = 5 ns. All times are "after TX closes".
- **Master settings**: delay after each gate (default 20 ms), stop after (default 3600 s), turn RF off when done.
- **Recording**: one time-stamped folder per run with `.dat` frames, PNG / TIFF images, `sweep.csv`, `settings.txt`
  and, with **Generate video**, `video.mp4`.
- **2D map**: raw, echo - air, echo - no-echo, phase, reflection coefficient (vs silicon) and acoustic impedance (MRayl).
  Trace over the whole frame, one pixel or an ROI.
- **3D view**: pick start and stop gate step (start = 0 um); depth = steps x 5 ns x c / 2. XY, XZ and YZ views; **Napari** opens the stack in 3D.
- **Pulse and echo simulator**: silicon die plus up to 5 layers, echoes per interface, up to three gates. No imager needed.

Settings are remembered between sessions. Edit the constants at the top of the file for other defaults.

## Status

The acquisition code path was tested with a simulated imager only. Check delays, limits and RF-off behaviour on the real
hardware before unattended runs.
