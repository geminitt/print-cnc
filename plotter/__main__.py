"""Ordinary Python entry point, with Pixi optional for development."""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

from .adapters import JsonlSource, MockSource
from .gcode import Job, Profile, build_job, read_json, save_job
from .images import read_jpg

LOG = logging.getLogger(__name__)


def simulation_profile() -> Profile:
    import json

    return Profile.from_dict(
        json.loads(
            files("plotter").joinpath("profiles/simulation.json").read_text(encoding="utf-8")
        )
    )


def convert(
    input_path: Path,
    output_path: Path,
    profile: Profile,
    threshold: int = 128,
    resolution: int = 256,
) -> Job:
    if input_path.resolve() in (
        output_path.with_suffix(".json").resolve(),
        output_path.with_suffix(".gcode").resolve(),
    ):
        raise ValueError("Output must not overwrite the input image")
    strokes, source = read_jpg(
        input_path, profile.width_mm, profile.height_mm, profile.margin_mm, threshold, resolution
    )
    job = build_job(strokes, profile, source)
    save_job(job, output_path)
    return job


def make_demo(output_dir: Path) -> Path:
    from PIL import Image, ImageDraw

    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.line((15, 20, 100, 20), fill="black", width=3)
    draw.rectangle((15, 45, 100, 135), outline="black", width=3)
    draw.ellipse((130, 35, 220, 125), outline="black", width=3)
    image.save(output_dir / "sample.jpg", quality=95)
    job_path = output_dir / "sample.json"
    convert(output_dir / "sample.jpg", job_path, simulation_profile())
    return job_path


def prepare_window() -> None:
    """Small file-preparation launcher; no drawing editor or machine controls."""
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk
    except ImportError as exc:
        raise ValueError(
            "Tkinter is missing; install your Python distribution's Tk package"
        ) from exc
    from .gui import MonitorWindow

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise ValueError(f"Cannot open the GUI display: {exc}") from exc
    root.title("JPG preparation — SIMULATION ONLY")
    root.geometry("660x300")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="JPG → XY Plotter", font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="SIMULATION ONLY — machine configuration is not yet confirmed",
        foreground="#a34216",
    ).pack(anchor="w", pady=10)
    ttk.Label(
        frame,
        text="Choose a JPG to extract black/white boundaries, save the draft job,\n"
        "and open a read-only mock execution monitor.",
    ).pack(anchor="w")
    status = ttk.Label(frame, text="No hardware connection or machine commands.", wraplength=600)
    status.pack(anchor="w", pady=12)
    results: queue.Queue = queue.Queue()
    closed = threading.Event()

    def choose() -> None:
        image_path = filedialog.askopenfilename(
            parent=root, title="Choose JPG", filetypes=[("JPEG image", "*.jpg *.jpeg *.JPG *.JPEG")]
        )
        if not image_path:
            return
        output_path = filedialog.asksaveasfilename(
            parent=root,
            title="Save simulation job",
            defaultextension=".json",
            filetypes=[("Plotter job", "*.json")],
        )
        if not output_path:
            return
        job_path = Path(output_path).with_suffix(".json")
        choose_button.configure(state="disabled")
        status.configure(text="Processing JPG in a background worker…")

        def work() -> None:
            try:
                convert(Path(image_path), job_path, simulation_profile())
                results.put((True, job_path))
            except Exception as exc:
                LOG.exception("JPG preparation failed")
                results.put((False, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def poll() -> None:
        if closed.is_set():
            return
        try:
            success, payload = results.get_nowait()
        except queue.Empty:
            root.after(50, poll)
            return
        if success:
            frame.destroy()
            MonitorWindow(root, payload, MockSource())
        else:
            status.configure(text=f"Cannot prepare JPG: {payload}")
            choose_button.configure(state="normal")
            root.after(50, poll)

    def close() -> None:
        closed.set()
        root.destroy()

    choose_button = ttk.Button(frame, text="Choose JPG and prepare simulation", command=choose)
    choose_button.pack(anchor="w")
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(50, poll)
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JPG preparation and read-only XY plotter monitor")
    sub = parser.add_subparsers(dest="command")
    conversion = sub.add_parser("convert", help="Prepare JPG without a GUI")
    conversion.add_argument("image", type=Path)
    conversion.add_argument("--output", type=Path, default=Path("output/job.json"))
    conversion.add_argument("--profile", type=Path, help="Default: explicitly simulated example")
    conversion.add_argument("--threshold", type=int, default=128)
    conversion.add_argument("--resolution", type=int, default=256)
    monitor = sub.add_parser("monitor", help="Monitor mock playback or an append-only event file")
    monitor.add_argument("job", type=Path)
    sources = monitor.add_mutually_exclusive_group(required=True)
    sources.add_argument("--mock", action="store_true")
    sources.add_argument("--events", type=Path)
    monitor.add_argument(
        "--simulation-events",
        action="store_true",
        help="Required when the event file contains simulated data",
    )
    monitor.add_argument("--stale-seconds", type=float, default=5)
    monitor.add_argument(
        "--scenario",
        choices=("completed", "paused", "error", "disconnected", "unconfirmed"),
        default="completed",
    )
    demo = sub.add_parser("demo", help="Create an example JPG and run mock monitoring")
    demo.add_argument("--output-dir", type=Path, default=Path("output/demo"))
    demo.add_argument(
        "--headless", action="store_true", help="Verify mock events without a display"
    )
    sub.add_parser("profile", help="Print the simulation profile for reference")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command is None:
            prepare_window()
        elif args.command == "convert":
            profile = (
                Profile.from_dict(read_json(args.profile)) if args.profile else simulation_profile()
            )
            job = convert(args.image, args.output, profile, args.threshold, args.resolution)
            print(f"Prepared {len(job.strokes)} strokes / {len(job.instructions)} instructions")
            print(f"Job: {args.output.with_suffix('.json')} / {job.job_id}")
            print(
                "SIMULATION ONLY"
                if profile.simulation
                else "UNVERIFIED PROFILE: requires team review"
            )
        elif args.command == "monitor":
            from .gui import run_monitor

            source = (
                MockSource(args.scenario)
                if args.mock
                else JsonlSource(args.events, args.simulation_events)
            )
            run_monitor(args.job, source, args.stale_seconds)
        elif args.command == "demo":
            from .gcode import load_job
            from .progress import Monitor

            job_path = make_demo(args.output_dir)
            if args.headless:
                job = load_job(job_path)
                model = Monitor(job, True)
                for event in MockSource(delay=0).events(job, threading.Event()):
                    model.apply(event)
                if model.state != "completed":
                    raise ValueError("Mock did not confirm completion")
                print(
                    f"SIMULATION: {model.state}; {model.confirmed}/{len(job.instructions)} "
                    f"instructions; {model.completed_draws} drawn segments"
                )
                print(f"Job: {job_path}")
            else:
                from .gui import run_monitor

                run_monitor(job_path, MockSource())
        elif args.command == "profile":
            import json

            print(json.dumps(asdict(simulation_profile()), indent=2))
    except (OSError, ValueError, TypeError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
