<div align="center">

# print-cvc

![Python](https://img.shields.io/badge/Python-3.11%2B-498AF2?style=for-the-badge)
![Input](https://img.shields.io/badge/Input-JPG-A19654?style=for-the-badge)
![Status](https://img.shields.io/badge/Hardware-unverified-6B7F4E?style=for-the-badge)

**Prepare JPG boundaries for an XY pen plotter and monitor confirmed execution.**

</div>

---

## Implementation and validation status

**The JPG simulation implementation is available. Desktop validation and real-machine integration are still required. This is not a machine-ready release.**

| Component | Implemented and checked | Still requires hands-on validation |
|---|---|---|
| JPG processing | JPEG decoding, orientation, black/white boundary extraction, holes, disconnected strokes, scaling, and coordinate conversion; checked with generated JPG test images | Try the recipient's own images and assess whether the extracted outlines produce the intended drawing |
| G-code preparation | Configurable work area and pen commands, pen-up travel, pen-down drawing, bounds checks, and matching preview metadata; checked with the simulation profile and software fixtures | Confirm the actual firmware dialect, machine dimensions, origin, feed rates, pen commands, and settling delays with the controller teammate |
| Execution progress | Mock events and the draft file-event adapter; tested counts, pause/error/disconnect states, and explicit completion confirmation | Connect an adapter to genuine controller feedback and prove that reported counts mean finished execution |
| GUI | JPG preparation window and read-only monitor are implemented; queue handling and bounded preview updates have headless checks | Open and test the actual Tk windows on the recipient's desktop; rendering, resizing, interaction, and responsiveness have not been verified on a display |
| Python packaging | Wheel built, installed, and run outside the source tree with ordinary Python on Linux, without Pixi commands | Check installation and GUI startup on the recipient's actual OS/Python; fresh dependency downloads and Windows/macOS execution were not tested |

Verification recorded on 2026-11-08: **41 automated tests passed; one real-Tk test was skipped because the test environment could not connect to a graphical display.** Lint and formatting checks passed. Both source and installed-wheel headless demos completed using mock execution. The installation check used cached Pillow dependencies; it does not establish a fresh online installation or desktop GUI operation.

### Hands-on validation still required

Complete the following checks before calling the application ready for the intended machine:

1. **Install on the recipient's computer.** Follow [Install and open](#install-and-open), then run `python -m tkinter` and `python -m plotter demo --headless`. Confirm that Tk opens a window and that the command-line demo finishes. Pixi is not needed.
2. **Exercise the actual GUI.** Run `python -m plotter`, choose a JPG, save the job, and inspect the monitor. Check window resizing, the path preview, progress labels, error messages, and responsiveness during loading and playback. From a source checkout, also run `python -m unittest discover -s tests -p test_gui.py -v`; the real-Tk test must run successfully rather than skip.
3. **Assess the intended images.** Start with a line, rectangle, curve, and disconnected strokes, then use the recipient's real JPGs. Check orientation, proportions, margins, missing detail, and unwanted contours. Adjust threshold/resolution through the [conversion command](#prepare-a-jpg-without-a-gui). Outline tracing can produce two boundaries around a thick line; photographic grayscale, shading, and centerline tracing are not implemented. Other image formats are not implemented yet.
4. **Inspect all mock states on screen.** Run the `paused`, `error`, `disconnected`, and `unconfirmed` scenarios listed under [Feedback events](#feedback-events). Confirm that only executed drawing segments turn green, a disconnect preserves the last confirmed count, and `unconfirmed` does not declare completion even after all instruction counts arrive. If no further feedback arrives, the watchdog should report a disconnect.
5. **Agree on the real integration contract.** With the controller teammate, resolve the items in [Before machine integration](#before-machine-integration), replace the example profile with reviewed machine settings, and implement any adapter needed for the actual feedback protocol. The existing NDJSON interface is a draft; it is not an Arduino/GRBL integration.
6. **Validate on the physical plotter with the controller teammate.** Use a small known drawing and verify its size, orientation, pen lift between disconnected strokes, pen lowering, travel limits, and feed behavior. Compare actual movement and completion against the GUI. Also check pause, controller error, and lost feedback. A successful mock run or a controller acknowledgment of receipt does not pass these physical checks.

Firmware, motor control, G-code sending, and machine start/pause/stop commands belong to the controller teammate and are not included in this application. The remaining hardware work is an integration and experiment task, not a claim that those modules have already been implemented here.

---

## Install and open

Install Python 3.11 or newer. From the downloaded project folder, run:

```console
python -m pip install .
python -m plotter
```

The window lets you choose a JPG, save the prepared job, and view simulated execution. It creates a `.json` job and a `.gcode` file with the same base name. You can also run `xy-plotter` after installation. Pixi is **not required** to install or run the application.

If you receive a wheel instead of the source folder:

```console
python -m pip install print_cvc-0.1.0-py3-none-any.whl
python -m plotter
```

On Windows, `py` can replace `python`. If Linux reports an externally managed Python environment, use an ordinary Python virtual environment:

```console
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m plotter
```

The runtime dependency, Pillow, is installed by pip. Tkinter is supplied by the Python distribution. If Tkinter is missing on Debian/Ubuntu, install the distribution's `python3-tk` package; a Python virtual environment can also require `python3-venv`. Custom Python installations need their matching Tk package. A graphical desktop is required for the GUI. Check Tk separately with `python -m tkinter`.

> **Note:** The included machine profile and all default playback are **SIMULATION ONLY**. Pen transitions in that profile are comments. They do not lift or lower a physical pen. Do not send these example files to a machine.

---

## Prepare a JPG without a GUI

```console
python -m plotter convert drawing.jpg --output output/drawing.json
python -m plotter monitor output/drawing.json --mock
```

For a reproducible example without hardware:

```console
python -m plotter demo
python -m plotter demo --headless
```

The demo creates a real JPG containing a line, rectangle, and ellipse, plus its job and G-code. `--headless` exercises simulated execution without opening a window.

Optional conversion parameters:

```console
python -m plotter convert drawing.jpg --threshold 128 --resolution 256 --profile machine.json --output output/drawing.json
python -m plotter profile
```

`profile` prints the complete simulation profile as a reference. Machine profiles are explicit JSON objects with the same fields; there are no implicit hardware defaults. All profiles remain unverified until reviewed against the team's actual controller and pen mechanism.

| Setting | Meaning |
|---|---|
| `width_mm`, `height_mm`, `margin_mm` | Explicit machine rectangle and image margin |
| `draw_feed_mm_min`, `travel_feed_mm_min` | Requested G1 and G0 feed values; the firmware must support them |
| `pen_up`, `pen_down` | Ordered commands for each transition; allow M codes, Z-only G0/G1, and G4 P dwell |
| `simulation` | Whether the job is simulated; simulated comments are forbidden when false |
| `threshold` CLI option | Pixels with grayscale values below this value become dark; range 1–255 |
| `resolution` CLI option | Maximum sampled image dimension, 16–512 pixels; lower values reduce detail and instruction count |

The adapter checks JPEG file content, applies EXIF orientation, converts to grayscale, resizes, and traces dark-pixel boundaries. It retains holes and disconnected shapes. It removes exactly collinear boundary points, preserves the image aspect ratio, centers the full image, and converts image Y-down to machine Y-up. Output uses millimeters, bottom-left XY origin, absolute positions, and three decimal places. The initial physical pen position is unknown and is not fabricated in the preview.

This is **outline tracing**. A thick black line normally produces two boundaries. Photographs can produce many disconnected contours. Centerline tracing, shading/hatching, and grayscale reproduction are not implemented. Begin with high-contrast line art and inspect the preview before integration. Changing JPG resolution or threshold changes the geometry and job identity.

Limits: 20 MiB encoded JPG, 24 million original pixels, sampled dimensions at most 512 × 512, and at most 100,000 generated instructions. Blank images, corrupt files, invalid profiles, nonfinite/out-of-bounds coordinates, and strokes that collapse at output precision fail visibly.

---

## Draft controller contract

The team has not supplied firmware, pen commands, physical travel limits, or execution feedback. The interfaces below are a **proposed integration contract**, not a claim of compatibility with Arduino or GRBL. Firmware, sending, homing, motor control, and start/pause/stop commands remain the controller teammate's responsibility.

```text
JPG → grayscale/threshold → pixel boundaries → machine-space strokes
    → pen-up travel / pen-down drawing → validated job JSON + G-code

Separate controller → confirmed execution events → read-only monitor
```

### Job handoff

`plotter-job-v1` JSON contains the machine profile, source image SHA-256 and conversion settings, normalized strokes, ordered `instructions`, the complete G-code, and a SHA-256 `job_id`. Each instruction has `text`, `kind`, and optional machine-space `start`/`end`. Kinds are `setup`, `pen_up`, `travel`, `pen_down`, and `draw`.

The controller must execute the exact instruction order and preserve its index mapping. The G-code has two header comments; instruction index zero corresponds to physical line three. An event's `confirmed = N` means that instructions with zero-based indices below N have **finished execution**, including setup, pen transitions, travel, and drawing. It is a contiguous prefix, not a count of arbitrary acknowledgments. Multi-command pen transitions count as separate instructions. Simulation counts include synthetic pen-comment operations; they are mock-only and do not model firmware acknowledgments.

Use `plotter.gcode.load_job()` to validate handoff metadata and `validate_gcode(job, file_text)` to verify that the companion G-code matches. Validation covers this generator's exact emitted language. It is not a parser or safety validator for arbitrary G-code. The controller must check its own dialect, Z limits, servo values, travel behavior, dwell units, homing requirements, and physical pen transitions before executing any real job. A comment or an `ok` that means "queued" cannot prove motion completion.

The `job_id` is deterministic for a given prepared job. A new physical run of the same job must start a new event file and monitor session. Do not append a new run to an old event history. A future live protocol should add a controller-issued run identity before supporting resume or repeated runs.

### Feedback events

The Python `EventSource` protocol yields `ExecutionEvent` records. The provided file adapter tails an append-only UTF-8 NDJSON regular file. It waits for complete newline-terminated records, reads in a worker thread, and never sends commands.

```json
{"schema":"plotter-event-v1","job_id":"<job_id from job JSON>","sequence":1,"kind":"running","simulation":false,"confirmed":0}
{"schema":"plotter-event-v1","job_id":"<same job_id>","sequence":2,"kind":"progress","simulation":false,"confirmed":6}
```

| Field | Contract |
|---|---|
| `job_id` | Exact prepared job identity |
| `sequence` | Increasing nonnegative integer within one run; gaps allowed because counts are cumulative |
| `kind` | `running`, `progress`, `paused`, `completed`, `error`, `disconnected`, `heartbeat`, `submitted`, or `accepted` |
| `simulation` | Required boolean; must match the selected event-source mode |
| `confirmed` | Optional cumulative executed instruction prefix; required for `progress` and `completed` |
| `position` | Optional actual reported `[x_mm, y_mm]`; never inferred from sent commands |
| `message` | Optional short controller message |

`submitted` and `accepted` cannot carry executed counts or positions and do not refresh the execution-feedback watchdog. Duplicate or older sequence numbers are ignored. A fresh count cannot move backward or exceed the job. A `completed` event must explicitly provide the full instruction count. Reaching that count in a `progress` event leaves the job waiting for explicit completion. The displayed percentage measures **executed instructions**, not elapsed or remaining time. Only confirmed `draw` instructions become green.

If the controller reports only final completion, send no intermediate `confirmed` counts: the GUI displays unknown progress until the final event. If the controller only acknowledges receipt, actual execution progress remains unknown. Use `heartbeat` for connection evidence, without inventing a count. The controller must emit periodic fresh feedback during long moves and pauses, or set an appropriate `--stale-seconds` value. The default five-second timeout is a configurable monitor watchdog, not a measured machine deadline.

```console
python -m plotter monitor output/drawing.json --events controller.ndjson
```

A simulation-only job cannot be monitored as a real job. For explicitly simulated recorded events:

```console
python -m plotter monitor output/drawing.json --events simulation.ndjson --simulation-events
```

Disconnects and stale feedback preserve the last confirmed count without declaring success. Malformed, mismatched, truncated, or replaced event data stops the reader and shows the problem. Completion and errors are terminal; restart with a fresh session for a new run. There is no automatic resume or reconnect protocol.

Mock scenarios for development:

```console
python -m plotter monitor output/drawing.json --mock --scenario paused
python -m plotter monitor output/drawing.json --mock --scenario error
python -m plotter monitor output/drawing.json --mock --scenario disconnected
python -m plotter monitor output/drawing.json --mock --scenario unconfirmed
```

`unconfirmed` executes the entire mock instruction prefix but never issues a completed event. It demonstrates that instruction progress cannot independently close a job.

---

## Development and verification

Ordinary Python works for development too:

```console
python -m pip install .
python -m unittest discover -s tests -v
```

Pixi is optional for contributors only:

```console
pixi install
pixi run test
pixi run lint
pixi run demo
```

The initial Pixi manifest targets Linux; ordinary pip installation is the cross-platform end-user path. Tests cover exhaustive 3 × 3 binary masks, holes, disconnected boundaries, real JPEG conversion and orientation, coordinate validation, pen transitions, exact preview/G-code mapping, corrupted metadata, execution semantics, partial event records, mock states, and the installed CLI. The real-Tk integration test explicitly skips if Tk or a graphical display is unavailable. A skip is not GUI verification. No hardware validation is included.

Build a distributable wheel with ordinary Python:

```console
python -m pip install build
python -m build --wheel
```

The wheel packages the simulation profile. It requires Python and Pillow at installation time; it does not include Pixi, a Python interpreter, or firmware. There is no standalone `.exe` in this version.

Implementation references: [Pillow Image API](https://pillow.readthedocs.io/en/stable/reference/Image.html), [Pillow EXIF orientation](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose), and [Tkinter event/thread model](https://docs.python.org/3/library/tkinter.html#threading-model).

---

## Before machine integration

Confirm the actual firmware and supported G-code dialect; pen mechanism, commands, and settling delays; work area, origin, homing, XY/Z limits, and feed rates; the file/API handoff; and what feedback proves execution completion. Extend the draft adapter only after agreeing on that protocol. No serial controller or firmware is included here.
