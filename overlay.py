from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass, replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import mss
import numpy as np

from config import CONFIG, OverlayConfig
from detector import (
    BorderDetector,
    DetectionResult,
    PageGeometry,
    ThreeFrameStabilizer,
    annotate_detection,
    grid_lines,
    transform_geometry,
)
from windows_api import (
    Bounds,
    HotkeyListener,
    capture_client_frame,
    configure_overlay_window,
    find_target_window,
    get_client_bounds,
    get_toplevel_hwnd,
    intersect_bounds,
    position_overlay,
    set_per_monitor_dpi_awareness,
    target_is_active,
    virtual_screen_bounds,
)


PROJECT_DIR = Path(__file__).resolve().parent
PID_FILE = PROJECT_DIR / "overlay.pid"


@dataclass(slots=True)
class OverlayUpdate:
    target_hwnd: int | None
    client_bounds: Bounds | None
    geometry: PageGeometry | None


def setup_logging(config: OverlayConfig) -> logging.Logger:
    log_dir = PROJECT_DIR / config.log_dir_name
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("kuixiang-grid-overlay")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(log_dir / "overlay.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


def put_latest(target_queue: queue.Queue[OverlayUpdate], update: OverlayUpdate) -> None:
    try:
        while True:
            target_queue.get_nowait()
    except queue.Empty:
        pass
    target_queue.put_nowait(update)


class DetectionWorker:
    def __init__(self, config: OverlayConfig, output_queue: queue.Queue[OverlayUpdate], logger: logging.Logger) -> None:
        self.config = config
        self.output_queue = output_queue
        self.logger = logger
        self.detector = BorderDetector(config)
        self.stabilizer = ThreeFrameStabilizer(
            config.update_every_frames,
            config.keep_last_geometry_batches,
            config.geometry_switch_confirm_batches,
            config.geometry_degrade_confirm_batches,
        )
        self.stop_event = threading.Event()
        self.debug_event = threading.Event()
        self.last_active_at = 0.0
        self.tracked_target_hwnd: int | None = None
        self.last_client_size: tuple[int, int] | None = None
        self.was_active = False
        self.last_detection_signature: tuple[object, ...] | None = None
        self.last_capture_signature: tuple[object, ...] | None = None
        self.thread = threading.Thread(target=self._run, name="overlay-detector", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def request_debug_snapshot(self) -> None:
        self.debug_event.set()

    def _run(self) -> None:
        with mss.MSS() as screen_capture:
            while not self.stop_event.is_set():
                started = time.perf_counter()
                target_hwnd = find_target_window(self.config.target_title_keywords)
                client_bounds = get_client_bounds(target_hwnd) if target_hwnd is not None else None
                if target_hwnd != self.tracked_target_hwnd:
                    self.tracked_target_hwnd = target_hwnd
                    self.last_active_at = 0.0
                    self.last_client_size = None
                    self.last_detection_signature = None
                    self.last_capture_signature = None
                    self.stabilizer.reset()

                client_size = (
                    (client_bounds.width, client_bounds.height)
                    if client_bounds is not None
                    else None
                )
                if (
                    client_size is not None
                    and self.last_client_size is not None
                    and (
                        abs(client_size[0] - self.last_client_size[0]) > 3
                        or abs(client_size[1] - self.last_client_size[1]) > 3
                    )
                ):
                    self.stabilizer.reset()
                    self.last_detection_signature = None
                    put_latest(self.output_queue, OverlayUpdate(target_hwnd, client_bounds, None))
                self.last_client_size = client_size
                foreground_active = (
                    target_hwnd is not None
                    and client_bounds is not None
                    and target_is_active(target_hwnd)
                )
                if foreground_active:
                    self.last_active_at = time.monotonic()
                within_inactive_grace = (
                    self.last_active_at > 0
                    and (time.monotonic() - self.last_active_at) * 1000 <= self.config.inactive_grace_ms
                )
                active = (
                    target_hwnd is not None
                    and client_bounds is not None
                    and (
                        not self.config.hide_when_target_inactive
                        or foreground_active
                        or within_inactive_grace
                    )
                )
                if not active:
                    if self.was_active:
                        put_latest(self.output_queue, OverlayUpdate(target_hwnd, client_bounds, None))
                    self.was_active = False
                    self.stabilizer.reset()
                    self.last_detection_signature = None
                    self._sleep_remaining(started)
                    continue
                self.was_active = True

                # 优先直接读取目标客户区，避免叠加线或其他前景窗口进入检测帧形成反馈误框。
                capture = capture_client_frame(target_hwnd)
                capture_offset_x = 0
                capture_offset_y = 0
                capture_scale_x = 1.0
                capture_scale_y = 1.0
                capture_mode = "printwindow"
                if capture is not None:
                    frame = capture.image
                    capture_scale_x = capture.scale_x
                    capture_scale_y = capture.scale_y
                else:
                    capture_mode = "screen"
                    virtual_bounds = virtual_screen_bounds()
                    capture_bounds = intersect_bounds(client_bounds, virtual_bounds)
                    if capture_bounds is None or capture_bounds.width < 100 or capture_bounds.height < 100:
                        put_latest(self.output_queue, OverlayUpdate(target_hwnd, client_bounds, None))
                        self.stabilizer.reset()
                        self.last_detection_signature = None
                        self._sleep_remaining(started)
                        continue

                    raw = screen_capture.grab(
                        {
                            "left": capture_bounds.left,
                            "top": capture_bounds.top,
                            "width": capture_bounds.width,
                            "height": capture_bounds.height,
                        }
                    )
                    frame = np.asarray(raw, dtype=np.uint8)[:, :, :3]
                    capture_offset_x = capture_bounds.left - client_bounds.left
                    capture_offset_y = capture_bounds.top - client_bounds.top

                capture_signature = (
                    capture_mode,
                    round(capture_scale_x, 6),
                    round(capture_scale_y, 6),
                    frame.shape[1],
                    frame.shape[0],
                )
                if capture_signature != self.last_capture_signature:
                    self.logger.info(
                        "捕获映射 mode=%s frame=%dx%d scale=%.6f×%.6f client=%dx%d",
                        capture_mode,
                        frame.shape[1],
                        frame.shape[0],
                        capture_scale_x,
                        capture_scale_y,
                        client_bounds.width,
                        client_bounds.height,
                    )
                    self.last_capture_signature = capture_signature

                result = self.detector.detect(frame)
                geometry = result.geometry
                if geometry is not None:
                    geometry = transform_geometry(
                        geometry,
                        capture_scale_x,
                        capture_scale_y,
                        capture_offset_x,
                        capture_offset_y,
                    )
                single_corner = geometry is None and len(result.corners) == 1
                should_update, stable_geometry = self.stabilizer.push(
                    geometry,
                    suppress=single_corner,
                )
                if should_update:
                    put_latest(self.output_queue, OverlayUpdate(target_hwnd, client_bounds, stable_geometry))
                    detection_signature = (
                        target_hwnd,
                        stable_geometry.mode if stable_geometry else None,
                        stable_geometry.anchor_edge if stable_geometry else None,
                        round(stable_geometry.rect.left) if stable_geometry else None,
                        round(stable_geometry.rect.top) if stable_geometry else None,
                        round(stable_geometry.rect.right) if stable_geometry else None,
                        round(stable_geometry.rect.bottom) if stable_geometry else None,
                        single_corner,
                    )
                    if detection_signature != self.last_detection_signature:
                        self.logger.info(
                            "检测提交 target=%s mode=%s confidence=%s corners=%d rect=%s",
                            target_hwnd,
                            stable_geometry.mode if stable_geometry else "none",
                            f"{stable_geometry.confidence:.3f}" if stable_geometry else "-",
                            len(result.corners),
                            asdict(stable_geometry.rect) if stable_geometry else "-",
                        )
                        self.last_detection_signature = detection_signature

                if self.debug_event.is_set():
                    self.debug_event.clear()
                    save_diagnostics(frame, result, self.config, prefix="hotkey")
                    self.logger.info("已保存诊断截图")
                self._sleep_remaining(started)

    def _sleep_remaining(self, started: float) -> None:
        interval = self.config.capture_interval_ms / 1000.0
        remaining = interval - (time.perf_counter() - started)
        if remaining > 0:
            self.stop_event.wait(remaining)


class OverlayApp:
    def __init__(self, config: OverlayConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.update_queue: queue.Queue[OverlayUpdate] = queue.Queue(maxsize=1)
        self.command_queue: queue.Queue[str] = queue.Queue()
        self.user_enabled = True
        self.owner_hwnd: int | None = None
        self.overlay_visible = False
        self.last_visible_signature: tuple[object, ...] | None = None
        self.last_window_bounds: tuple[int, int, int, int] | None = None
        self.current_grid_tag: str | None = None
        self.grid_generation = 0

        self.root = tk.Tk(className="KuixiangGridOverlay")
        self.root.report_callback_exception = self._report_callback_exception
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.configure(bg=config.transparent_color)
        self.root.wm_attributes("-topmost", False)
        try:
            self.root.wm_attributes("-transparentcolor", config.transparent_color)
        except tk.TclError:
            self.logger.warning("当前 Tk 不支持透明色键，改用整体透明度")
        self.root.wm_attributes("-alpha", config.overlay_alpha)
        self.root.title("KuixiangGridOverlayInternal")
        self.canvas = tk.Canvas(self.root, bg=config.transparent_color, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.tk_child_hwnd = int(self.root.winfo_id())
        self.overlay_hwnd = get_toplevel_hwnd(self.tk_child_hwnd)
        self.logger.info("窗口句柄：TkChild=%s，TkTopLevel=%s", self.tk_child_hwnd, self.overlay_hwnd)

        self.worker = DetectionWorker(config, self.update_queue, logger)
        self.hotkeys = HotkeyListener(self.command_queue.put)

    def run(self) -> None:
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
        self.worker.start()
        self.hotkeys.start()
        self.root.after(30, self._poll)
        self.logger.info(
            "程序启动：纸张 %.3f×%.3f cm，网格 %.3f×%.3f cm，每 %d 帧更新一次",
            self.config.paper_width_cm,
            self.config.paper_height_cm,
            self.config.grid_width_cm,
            self.config.grid_height_cm,
            self.config.update_every_frames,
        )
        try:
            self.root.mainloop()
        finally:
            self.worker.stop()
            self.hotkeys.stop()
            PID_FILE.unlink(missing_ok=True)
            self.logger.info("程序已退出")

    def shutdown(self) -> None:
        self.root.after(0, self.root.destroy)

    def _report_callback_exception(self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback) -> None:
        self.logger.error("Tk 回调异常", exc_info=(exc_type, exc_value, exc_traceback))

    def _poll(self) -> None:
        try:
            while True:
                command = self.command_queue.get_nowait()
                if command == "toggle":
                    self.user_enabled = not self.user_enabled
                    self.logger.info("叠加层%s", "启用" if self.user_enabled else "隐藏")
                    if not self.user_enabled:
                        self.root.withdraw()
                elif command == "debug":
                    self.worker.request_debug_snapshot()
                elif command == "quit":
                    self.shutdown()
                    return
        except queue.Empty:
            pass

        latest: OverlayUpdate | None = None
        try:
            while True:
                latest = self.update_queue.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            try:
                self._apply_update(latest)
            except Exception:
                self.logger.exception("应用叠加层更新失败")
                self.root.withdraw()
                self.overlay_visible = False
        self.root.after(30, self._poll)

    def _apply_update(self, update: OverlayUpdate) -> None:
        if not self.user_enabled or update.target_hwnd is None or update.client_bounds is None or update.geometry is None:
            if self.overlay_visible:
                self.logger.info("叠加层已隐藏")
            self.root.withdraw()
            self.overlay_visible = False
            self.last_window_bounds = None
            return

        bounds = update.client_bounds
        lines = grid_lines(update.geometry, bounds.width, bounds.height, self.config)
        if not lines:
            if self.overlay_visible:
                self.logger.info("叠加层已隐藏：当前几何没有可绘制分割线")
            self.root.withdraw()
            self.overlay_visible = False
            self.last_window_bounds = None
            return

        signature = (
            update.target_hwnd,
            update.geometry.mode,
            update.geometry.anchor_edge,
            round(update.geometry.rect.left),
            round(update.geometry.rect.top),
            round(update.geometry.rect.right),
            round(update.geometry.rect.bottom),
            len(lines),
        )
        bounds_signature = (bounds.left, bounds.top, bounds.width, bounds.height)

        if self.owner_hwnd != update.target_hwnd:
            configure_overlay_window(self.overlay_hwnd, update.target_hwnd)
            self.owner_hwnd = update.target_hwnd

        signature_changed = signature != self.last_visible_signature
        if signature_changed or self.current_grid_tag is None:
            self.grid_generation += 1
            new_tag = f"grid_{self.grid_generation}"
            self.canvas.configure(width=bounds.width, height=bounds.height)
            for x1, y1, x2, y2, major in lines:
                self.canvas.create_line(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=self.config.major_grid_color if major else self.config.grid_color,
                    width=self.config.major_line_width if major else self.config.grid_line_width,
                    tags=(new_tag,),
                )
            # 先创建新网格，再删除旧网格，切换时不会出现空白帧。
            old_tag = self.current_grid_tag
            self.current_grid_tag = new_tag
            if old_tag is not None:
                self.canvas.delete(old_tag)
            self.last_visible_signature = signature

        if not self.overlay_visible:
            self.root.deiconify()
        if not self.overlay_visible or bounds_signature != self.last_window_bounds:
            position_overlay(self.overlay_hwnd, bounds)
            self.last_window_bounds = bounds_signature
        self.root.update_idletasks()

        if not self.overlay_visible or signature_changed:
            self.logger.info(
                "叠加层已显示 hwnd=%s mode=%s lines=%d rect=%s",
                self.overlay_hwnd,
                update.geometry.mode,
                len(lines),
                asdict(update.geometry.rect),
            )
        self.overlay_visible = True


def geometry_to_dict(geometry: PageGeometry | None) -> dict[str, object] | None:
    return asdict(geometry) if geometry is not None else None


def save_diagnostics(
    frame_bgr: np.ndarray,
    result: DetectionResult,
    config: OverlayConfig,
    prefix: str = "diagnose",
) -> Path:
    output_dir = PROJECT_DIR / config.debug_dir_name
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"{prefix}-{timestamp}"
    cv2.imwrite(str(output_dir / f"{stem}-frame.png"), frame_bgr)
    cv2.imwrite(str(output_dir / f"{stem}-mask.png"), result.mask)
    cv2.imwrite(str(output_dir / f"{stem}-annotated.png"), annotate_detection(frame_bgr, result, config))
    payload = {
        "geometry": geometry_to_dict(result.geometry),
        "horizontal_segments": [asdict(item) for item in result.horizontal_segments],
        "vertical_segments": [asdict(item) for item in result.vertical_segments],
        "corners": [
            {"x": item.x, "y": item.y, "kind": item.kind, "strength": item.strength}
            for item in result.corners
        ],
    }
    json_path = output_dir / f"{stem}-result.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def diagnose_once(config: OverlayConfig, logger: logging.Logger) -> int:
    target_hwnd = find_target_window(config.target_title_keywords)
    if target_hwnd is None:
        logger.error("未找到奎享雕刻窗口")
        return 2
    client_bounds = get_client_bounds(target_hwnd)
    if client_bounds is None:
        logger.error("无法读取目标窗口客户区")
        return 2
    capture_bounds = intersect_bounds(client_bounds, virtual_screen_bounds())
    if capture_bounds is None:
        logger.error("目标窗口不在可见屏幕区域")
        return 2
    capture = capture_client_frame(target_hwnd)
    capture_scale_x = 1.0
    capture_scale_y = 1.0
    capture_offset_x = 0
    capture_offset_y = 0
    if capture is not None:
        frame = capture.image
        capture_scale_x = capture.scale_x
        capture_scale_y = capture.scale_y
    else:
        with mss.MSS() as screen_capture:
            raw = screen_capture.grab(asdict(capture_bounds))
        frame = np.asarray(raw, dtype=np.uint8)[:, :, :3]
        capture_offset_x = capture_bounds.left - client_bounds.left
        capture_offset_y = capture_bounds.top - client_bounds.top
    result = BorderDetector(config).detect(frame)
    client_geometry = (
        transform_geometry(
            result.geometry,
            capture_scale_x,
            capture_scale_y,
            capture_offset_x,
            capture_offset_y,
        )
        if result.geometry is not None
        else None
    )
    path = save_diagnostics(frame, result, config)
    print(
        json.dumps(
            {
                "result": str(path),
                "capture_scale": [capture_scale_x, capture_scale_y],
                "capture_geometry": geometry_to_dict(result.geometry),
                "client_geometry": geometry_to_dict(client_geometry),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if client_geometry is not None else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="奎享雕刻纸张网格半透明叠加层")
    parser.add_argument("--paper-width", type=float)
    parser.add_argument("--paper-height", type=float)
    parser.add_argument("--grid-width", type=float)
    parser.add_argument("--grid-height", type=float)
    parser.add_argument("--orientation", choices=("portrait", "landscape", "auto"))
    parser.add_argument("--diagnose-once", action="store_true")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> OverlayConfig:
    replacements: dict[str, object] = {}
    if args.paper_width is not None:
        replacements["paper_width_cm"] = args.paper_width
    if args.paper_height is not None:
        replacements["paper_height_cm"] = args.paper_height
    if args.grid_width is not None:
        replacements["grid_width_cm"] = args.grid_width
    if args.grid_height is not None:
        replacements["grid_height_cm"] = args.grid_height
    if args.orientation is not None:
        replacements["paper_orientation"] = args.orientation
    config = replace(CONFIG, **replacements)
    if min(config.paper_width_cm, config.paper_height_cm, config.grid_width_cm, config.grid_height_cm) <= 0:
        raise ValueError("纸张和网格尺寸必须大于 0")
    return config


def main() -> int:
    set_per_monitor_dpi_awareness()
    args = parse_args()
    config = config_from_args(args)
    logger = setup_logging(config)
    if args.diagnose_once:
        return diagnose_once(config, logger)

    app = OverlayApp(config, logger)
    signal.signal(signal.SIGINT, lambda *_args: app.shutdown())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_args: app.shutdown())
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

