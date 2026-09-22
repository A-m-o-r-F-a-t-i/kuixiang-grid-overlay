from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import product
from statistics import median
from typing import Literal

import cv2
import numpy as np

from config import OverlayConfig


Orientation = Literal["portrait", "landscape"]
Mode = Literal["full", "partial-horizontal", "partial-vertical", "partial-diagonal"]


@dataclass(frozen=True, slots=True)
class RectF:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class Segment:
    orientation: Literal["h", "v"]
    coord: float
    start: float
    end: float
    strength: float

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Corner:
    x: float
    y: float
    kind: Literal["TL", "TR", "BL", "BR"]
    horizontal: Segment
    vertical: Segment
    strength: float


@dataclass(frozen=True, slots=True)
class PageGeometry:
    rect: RectF
    mode: Mode
    confidence: float
    orientation: Orientation
    paper_width_cm: float
    paper_height_cm: float
    px_per_cm_x: float
    px_per_cm_y: float
    draw_vertical: bool
    draw_horizontal: bool
    anchor_edge: str | None = None
    corners: tuple[tuple[float, float, str], ...] = ()


@dataclass(slots=True)
class DetectionResult:
    geometry: PageGeometry | None
    mask: np.ndarray
    horizontal_segments: list[Segment]
    vertical_segments: list[Segment]
    corners: list[Corner]


class BorderDetector:
    """检测品红色纸张边框，并在完整矩形缺失时使用两个直角降级。"""

    def __init__(self, config: OverlayConfig) -> None:
        self.config = config

    def detect(self, frame_bgr: np.ndarray) -> DetectionResult:
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("frame_bgr 必须是 BGR 三通道图像")
        mask = self._magenta_mask(frame_bgr)
        horizontal, vertical = self._extract_segments(mask)
        corners = self._extract_corners(mask, horizontal, vertical)
        geometry = self._find_full_geometry(frame_bgr, corners)
        if geometry is None:
            geometry = self._find_three_corner_geometry(frame_bgr, corners)
        if geometry is None:
            geometry = self._find_partial_geometry(frame_bgr, corners)
        return DetectionResult(geometry, mask, horizontal, vertical, corners)

    def _magenta_mask(self, frame_bgr: np.ndarray) -> np.ndarray:
        b, g, r = cv2.split(frame_bgr)
        r16 = r.astype(np.int16)
        g16 = g.astype(np.int16)
        b16 = b.astype(np.int16)

        delta = self.config.magenta_min_channel_delta
        min_rb = np.minimum(r16, b16)
        max_rb = np.maximum(r16, b16)
        chroma = (r16 - g16 >= delta) & (b16 - g16 >= delta) & (min_rb >= 35)
        balanced = (max_rb - min_rb) <= np.maximum(70, min_rb // 2)

        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        hsv_magenta = (
            (hue >= 132)
            & (hue <= 179)
            & (saturation >= self.config.magenta_min_saturation)
            & (value >= self.config.magenta_min_value)
        )

        strong_channel = (r16 - g16 >= 20) & (b16 - g16 >= 20) & (min_rb >= 55)
        mask = ((chroma & balanced & hsv_magenta) | (strong_channel & balanced)).astype(np.uint8) * 255
        # 单像素边框在部分缩放比例下很常见，不能使用会将其抹除的中值滤波。
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), dtype=np.uint8))

    def _extract_segments(self, mask: np.ndarray) -> tuple[list[Segment], list[Segment]]:
        height, width = mask.shape
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, width // 80), 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, height // 80)))
        h_mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, h_kernel)
        v_mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, v_kernel)

        horizontal_raw = self._hough(h_mask, "h")
        vertical_raw = self._hough(v_mask, "v")
        coord_tolerance = max(3.0, min(width, height) * 0.004)
        horizontal = self._merge_segments(horizontal_raw, coord_tolerance, width * 0.035)
        vertical = self._merge_segments(vertical_raw, coord_tolerance, height * 0.035)

        horizontal.sort(key=lambda segment: segment.length, reverse=True)
        vertical.sort(key=lambda segment: segment.length, reverse=True)
        return horizontal[:32], vertical[:32]

    def _hough(self, binary: np.ndarray, orientation: Literal["h", "v"]) -> list[Segment]:
        height, width = binary.shape
        primary = width if orientation == "h" else height
        minimum_length = max(36, int(primary * 0.06))
        lines = cv2.HoughLinesP(
            binary,
            rho=1,
            theta=np.pi / 360,
            threshold=max(18, int(primary * 0.018)),
            minLineLength=minimum_length,
            maxLineGap=max(8, int(primary * 0.025)),
        )
        if lines is None:
            return []
        output: list[Segment] = []
        for packed in lines[:, 0, :]:
            x1, y1, x2, y2 = map(float, packed)
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            if orientation == "h":
                if dx < minimum_length or dy > max(3.0, dx * 0.055):
                    continue
                output.append(Segment("h", (y1 + y2) / 2, min(x1, x2), max(x1, x2), dx / width))
            else:
                if dy < minimum_length or dx > max(3.0, dy * 0.055):
                    continue
                output.append(Segment("v", (x1 + x2) / 2, min(y1, y2), max(y1, y2), dy / height))
        return output

    @staticmethod
    def _merge_segments(segments: list[Segment], coord_tolerance: float, gap_tolerance: float) -> list[Segment]:
        if not segments:
            return []
        segments = sorted(segments, key=lambda item: (item.coord, item.start))
        coord_groups: list[list[Segment]] = []
        for segment in segments:
            if not coord_groups:
                coord_groups.append([segment])
                continue
            current_coord = sum(item.coord for item in coord_groups[-1]) / len(coord_groups[-1])
            if abs(segment.coord - current_coord) <= coord_tolerance:
                coord_groups[-1].append(segment)
            else:
                coord_groups.append([segment])

        merged: list[Segment] = []
        for group in coord_groups:
            coordinate = float(median(item.coord for item in group))
            intervals = sorted((item.start, item.end, item.strength) for item in group)
            start, end, strength = intervals[0]
            strengths = [strength]
            for next_start, next_end, next_strength in intervals[1:]:
                if next_start <= end + gap_tolerance:
                    end = max(end, next_end)
                    strengths.append(next_strength)
                else:
                    merged.append(Segment(group[0].orientation, coordinate, start, end, max(strengths)))
                    start, end, strengths = next_start, next_end, [next_strength]
            merged.append(Segment(group[0].orientation, coordinate, start, end, max(strengths)))
        return merged

    def _extract_corners(
        self,
        mask: np.ndarray,
        horizontal: list[Segment],
        vertical: list[Segment],
    ) -> list[Corner]:
        height, width = mask.shape
        endpoint_tolerance = max(10.0, min(width, height) * 0.025)
        corners: list[Corner] = []
        for h_segment in horizontal:
            for v_segment in vertical:
                x = v_segment.coord
                y = h_segment.coord
                if not (h_segment.start - endpoint_tolerance <= x <= h_segment.end + endpoint_tolerance):
                    continue
                if not (v_segment.start - endpoint_tolerance <= y <= v_segment.end + endpoint_tolerance):
                    continue
                h_distance = min(abs(x - h_segment.start), abs(x - h_segment.end))
                v_distance = min(abs(y - v_segment.start), abs(y - v_segment.end))
                if h_distance > endpoint_tolerance or v_distance > endpoint_tolerance:
                    continue
                strength = self._corner_density(mask, x, y)
                if strength < 0.025:
                    continue
                horizontal_side = "L" if abs(x - h_segment.start) <= abs(x - h_segment.end) else "R"
                vertical_side = "T" if abs(y - v_segment.start) <= abs(y - v_segment.end) else "B"
                corners.append(Corner(x, y, f"{vertical_side}{horizontal_side}", h_segment, v_segment, strength))

        deduplicated: list[Corner] = []
        for corner in sorted(corners, key=lambda item: item.strength, reverse=True):
            if any(
                item.kind == corner.kind and math.hypot(item.x - corner.x, item.y - corner.y) <= endpoint_tolerance / 2
                for item in deduplicated
            ):
                continue
            deduplicated.append(corner)
        return deduplicated[:24]

    @staticmethod
    def _corner_density(mask: np.ndarray, x: float, y: float) -> float:
        radius = 7
        x0 = max(0, int(round(x)) - radius)
        x1 = min(mask.shape[1], int(round(x)) + radius + 1)
        y0 = max(0, int(round(y)) - radius)
        y1 = min(mask.shape[0], int(round(y)) + radius + 1)
        region = mask[y0:y1, x0:x1]
        if region.size == 0:
            return 0.0
        return float(np.count_nonzero(region)) / float(region.size)

    def _orientation_options(self) -> list[tuple[Orientation, float, float, float]]:
        portrait = ("portrait", self.config.paper_width_cm, self.config.paper_height_cm, 1.0)
        landscape = ("landscape", self.config.paper_height_cm, self.config.paper_width_cm, 0.94)
        if self.config.paper_orientation == "landscape":
            return [landscape]
        if self.config.paper_orientation == "auto":
            return [portrait, landscape]
        return [portrait]

    def _find_full_geometry(self, frame_bgr: np.ndarray, corners: list[Corner]) -> PageGeometry | None:
        by_kind: dict[str, list[Corner]] = defaultdict(list)
        for corner in corners:
            by_kind[corner.kind].append(corner)
        tolerance = max(8.0, min(frame_bgr.shape[:2]) * 0.018)
        candidates: list[PageGeometry] = []
        for top_left in by_kind["TL"]:
            for top_right in by_kind["TR"]:
                if abs(top_left.y - top_right.y) > tolerance or top_right.x - top_left.x < frame_bgr.shape[1] * 0.18:
                    continue
                for bottom_left in by_kind["BL"]:
                    if abs(top_left.x - bottom_left.x) > tolerance or bottom_left.y - top_left.y < frame_bgr.shape[0] * 0.18:
                        continue
                    bottom_right = self._nearest_corner(by_kind["BR"], top_right.x, bottom_left.y, tolerance)
                    if bottom_right is None:
                        continue
                    rect = RectF(
                        float(median((top_left.x, bottom_left.x))),
                        float(median((top_left.y, top_right.y))),
                        float(median((top_right.x, bottom_right.x))),
                        float(median((bottom_left.y, bottom_right.y))),
                    )
                    if rect.width <= 0 or rect.height <= 0:
                        continue
                    for orientation, paper_width, paper_height, bias in self._orientation_options():
                        px_x = rect.width / paper_width
                        px_y = rect.height / paper_height
                        anisotropy = abs(px_x - px_y) / max(1.0, (px_x + px_y) / 2)
                        if anisotropy > 0.16:
                            continue
                        brightness = self._inside_brightness(frame_bgr, rect)
                        if brightness < 110:
                            continue
                        corner_strength = sum(
                            item.strength for item in (top_left, top_right, bottom_left, bottom_right)
                        ) / 4
                        confidence = min(
                            0.99,
                            bias
                            * (
                                0.44
                                + 0.22 * math.exp(-anisotropy * 8)
                                + 0.18 * min(1.0, corner_strength * 6)
                                + 0.16 * min(1.0, brightness / 220)
                            ),
                        )
                        candidates.append(
                            PageGeometry(
                                rect,
                                "full",
                                confidence,
                                orientation,
                                paper_width,
                                paper_height,
                                px_x,
                                px_y,
                                True,
                                True,
                                None,
                                tuple((item.x, item.y, item.kind) for item in (top_left, top_right, bottom_left, bottom_right)),
                            )
                        )
        return max(candidates, key=lambda item: item.confidence, default=None)

    def _find_three_corner_geometry(
        self,
        frame_bgr: np.ndarray,
        corners: list[Corner],
    ) -> PageGeometry | None:
        """由任意三个兼容直角重建完整纸张矩形。"""

        by_kind: dict[str, list[Corner]] = defaultdict(list)
        for corner in corners:
            by_kind[corner.kind].append(corner)

        observed_sets = (
            ("TL", "TR", "BL"),
            ("TL", "TR", "BR"),
            ("TL", "BL", "BR"),
            ("TR", "BL", "BR"),
        )
        frame_height, frame_width = frame_bgr.shape[:2]
        tolerance = max(8.0, min(frame_width, frame_height) * 0.022)
        candidates: list[PageGeometry] = []

        for kinds in observed_sets:
            if any(not by_kind[kind] for kind in kinds):
                continue
            for selected in product(*(by_kind[kind] for kind in kinds)):
                selected_by_kind = dict(zip(kinds, selected))
                left_values = [corner.x for kind, corner in selected_by_kind.items() if kind.endswith("L")]
                right_values = [corner.x for kind, corner in selected_by_kind.items() if kind.endswith("R")]
                top_values = [corner.y for kind, corner in selected_by_kind.items() if kind.startswith("T")]
                bottom_values = [corner.y for kind, corner in selected_by_kind.items() if kind.startswith("B")]

                side_values = (left_values, right_values, top_values, bottom_values)
                if any(not values for values in side_values):
                    continue
                if any(len(values) > 1 and max(values) - min(values) > tolerance for values in side_values):
                    continue

                rect = RectF(
                    float(median(left_values)),
                    float(median(top_values)),
                    float(median(right_values)),
                    float(median(bottom_values)),
                )
                if rect.width < frame_width * 0.18 or rect.height < frame_height * 0.18:
                    continue

                for orientation, paper_width, paper_height, bias in self._orientation_options():
                    px_x = rect.width / paper_width
                    px_y = rect.height / paper_height
                    anisotropy = abs(px_x - px_y) / max(1.0, (px_x + px_y) / 2)
                    if anisotropy > 0.18:
                        continue
                    brightness = self._inside_brightness(frame_bgr, rect)
                    if brightness < 110:
                        continue
                    corner_strength = sum(item.strength for item in selected) / len(selected)
                    confidence = min(
                        0.965,
                        bias
                        * (
                            0.48
                            + 0.22 * math.exp(-anisotropy * 8)
                            + 0.18 * min(1.0, corner_strength * 6)
                            + 0.12 * min(1.0, brightness / 220)
                        ),
                    )
                    candidates.append(
                        PageGeometry(
                            rect,
                            "full",
                            confidence,
                            orientation,
                            paper_width,
                            paper_height,
                            px_x,
                            px_y,
                            True,
                            True,
                            None,
                            tuple((item.x, item.y, item.kind) for item in selected),
                        )
                    )

        return max(candidates, key=lambda item: item.confidence, default=None)

    @staticmethod
    def _nearest_corner(corners: list[Corner], x: float, y: float, tolerance: float) -> Corner | None:
        nearby = [corner for corner in corners if abs(corner.x - x) <= tolerance and abs(corner.y - y) <= tolerance]
        return max(nearby, key=lambda item: item.strength, default=None)

    @staticmethod
    def _inside_brightness(frame_bgr: np.ndarray, rect: RectF) -> float:
        x0 = max(0, min(frame_bgr.shape[1] - 1, int(rect.left + rect.width * 0.08)))
        x1 = max(x0 + 1, min(frame_bgr.shape[1], int(rect.right - rect.width * 0.08)))
        y0 = max(0, min(frame_bgr.shape[0] - 1, int(rect.top + rect.height * 0.08)))
        y1 = max(y0 + 1, min(frame_bgr.shape[0], int(rect.bottom - rect.height * 0.08)))
        region = frame_bgr[y0:y1, x0:x1]
        if region.size == 0:
            return 0.0
        return float(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).mean())

    def _find_partial_geometry(self, frame_bgr: np.ndarray, corners: list[Corner]) -> PageGeometry | None:
        height, width = frame_bgr.shape[:2]
        tolerance = max(9.0, min(width, height) * 0.02)
        by_kind: dict[str, list[Corner]] = defaultdict(list)
        for corner in corners:
            by_kind[corner.kind].append(corner)

        candidates: list[PageGeometry] = []
        candidates.extend(self._horizontal_corner_pairs(by_kind["TL"], by_kind["TR"], "top", width, height, tolerance))
        candidates.extend(self._horizontal_corner_pairs(by_kind["BL"], by_kind["BR"], "bottom", width, height, tolerance))
        candidates.extend(self._vertical_corner_pairs(by_kind["TL"], by_kind["BL"], "left", width, height, tolerance))
        candidates.extend(self._vertical_corner_pairs(by_kind["TR"], by_kind["BR"], "right", width, height, tolerance))
        candidates.extend(self._diagonal_corner_pairs(by_kind["TL"], by_kind["BR"], width, height))
        candidates.extend(self._diagonal_corner_pairs(by_kind["TR"], by_kind["BL"], width, height))
        return max(candidates, key=lambda item: item.confidence, default=None)

    def _horizontal_corner_pairs(
        self,
        left_corners: list[Corner],
        right_corners: list[Corner],
        edge: Literal["top", "bottom"],
        frame_width: int,
        frame_height: int,
        tolerance: float,
    ) -> list[PageGeometry]:
        output: list[PageGeometry] = []
        for left_corner in left_corners:
            for right_corner in right_corners:
                if abs(left_corner.y - right_corner.y) > tolerance:
                    continue
                span = right_corner.x - left_corner.x
                if span < frame_width * 0.18:
                    continue
                anchor_y = float(median((left_corner.y, right_corner.y)))
                observed_arm = max(
                    self._vertical_inward_length(left_corner, edge),
                    self._vertical_inward_length(right_corner, edge),
                )
                for orientation, paper_width, paper_height, bias in self._orientation_options():
                    px_per_cm = span / paper_width
                    inferred_height = px_per_cm * paper_height
                    if inferred_height < observed_arm * 0.8 or inferred_height > frame_height * 3.5:
                        continue
                    # 只有同一水平边的两个直角时，只在已实际观察到的两条垂直边范围内保留分割，
                    # 避免按完整纸高推算后把网格画到滚动条、按钮或窗口外区域。
                    visible_height = min(inferred_height, max(1.0, observed_arm))
                    top = anchor_y if edge == "top" else anchor_y - visible_height
                    bottom = anchor_y + visible_height if edge == "top" else anchor_y
                    confidence = min(
                        0.9,
                        bias
                        * (
                            0.52
                            + 0.18 * min(1.0, span / (frame_width * 0.55))
                            + 0.18 * min(1.0, (left_corner.strength + right_corner.strength) * 3)
                            + 0.12 * min(1.0, observed_arm / max(1.0, inferred_height * 0.2))
                        ),
                    )
                    output.append(
                        PageGeometry(
                            RectF(left_corner.x, top, right_corner.x, bottom),
                            "partial-horizontal",
                            confidence,
                            orientation,
                            paper_width,
                            paper_height,
                            px_per_cm,
                            px_per_cm,
                            True,
                            False,
                            edge,
                            ((left_corner.x, left_corner.y, left_corner.kind), (right_corner.x, right_corner.y, right_corner.kind)),
                        )
                    )
        return output

    def _vertical_corner_pairs(
        self,
        top_corners: list[Corner],
        bottom_corners: list[Corner],
        edge: Literal["left", "right"],
        frame_width: int,
        frame_height: int,
        tolerance: float,
    ) -> list[PageGeometry]:
        output: list[PageGeometry] = []
        for top_corner in top_corners:
            for bottom_corner in bottom_corners:
                if abs(top_corner.x - bottom_corner.x) > tolerance:
                    continue
                span = bottom_corner.y - top_corner.y
                if span < frame_height * 0.18:
                    continue
                anchor_x = float(median((top_corner.x, bottom_corner.x)))
                observed_arm = max(
                    self._horizontal_inward_length(top_corner, edge),
                    self._horizontal_inward_length(bottom_corner, edge),
                )
                for orientation, paper_width, paper_height, bias in self._orientation_options():
                    px_per_cm = span / paper_height
                    inferred_width = px_per_cm * paper_width
                    if inferred_width < observed_arm * 0.8 or inferred_width > frame_width * 3.5:
                        continue
                    # 只有同一垂直边的两个直角时，只在已实际观察到的两条水平边范围内保留分割。
                    visible_width = min(inferred_width, max(1.0, observed_arm))
                    left = anchor_x if edge == "left" else anchor_x - visible_width
                    right = anchor_x + visible_width if edge == "left" else anchor_x
                    confidence = min(
                        0.9,
                        bias
                        * (
                            0.52
                            + 0.18 * min(1.0, span / (frame_height * 0.55))
                            + 0.18 * min(1.0, (top_corner.strength + bottom_corner.strength) * 3)
                            + 0.12 * min(1.0, observed_arm / max(1.0, inferred_width * 0.2))
                        ),
                    )
                    output.append(
                        PageGeometry(
                            RectF(left, top_corner.y, right, bottom_corner.y),
                            "partial-vertical",
                            confidence,
                            orientation,
                            paper_width,
                            paper_height,
                            px_per_cm,
                            px_per_cm,
                            False,
                            True,
                            edge,
                            ((top_corner.x, top_corner.y, top_corner.kind), (bottom_corner.x, bottom_corner.y, bottom_corner.kind)),
                        )
                    )
        return output

    def _diagonal_corner_pairs(
        self,
        first_corners: list[Corner],
        second_corners: list[Corner],
        frame_width: int,
        frame_height: int,
    ) -> list[PageGeometry]:
        output: list[PageGeometry] = []
        for first in first_corners:
            for second in second_corners:
                rect = RectF(min(first.x, second.x), min(first.y, second.y), max(first.x, second.x), max(first.y, second.y))
                if rect.width < frame_width * 0.18 or rect.height < frame_height * 0.18:
                    continue
                for orientation, paper_width, paper_height, bias in self._orientation_options():
                    px_x = rect.width / paper_width
                    px_y = rect.height / paper_height
                    anisotropy = abs(px_x - px_y) / max(1.0, (px_x + px_y) / 2)
                    if anisotropy > 0.18:
                        continue
                    confidence = min(
                        0.86,
                        bias
                        * (
                            0.58
                            + 0.18 * math.exp(-anisotropy * 8)
                            + 0.24 * min(1.0, (first.strength + second.strength) * 3)
                        ),
                    )
                    output.append(
                        PageGeometry(
                            rect,
                            "partial-diagonal",
                            confidence,
                            orientation,
                            paper_width,
                            paper_height,
                            px_x,
                            px_y,
                            True,
                            True,
                            None,
                            ((first.x, first.y, first.kind), (second.x, second.y, second.kind)),
                        )
                    )
        return output

    @staticmethod
    def _vertical_inward_length(corner: Corner, edge: str) -> float:
        return corner.vertical.end - corner.y if edge == "top" else corner.y - corner.vertical.start

    @staticmethod
    def _horizontal_inward_length(corner: Corner, edge: str) -> float:
        return corner.horizontal.end - corner.x if edge == "left" else corner.x - corner.horizontal.start


class ThreeFrameStabilizer:
    """按三帧批次稳定几何，并抑制证据降级和错误页面切换。"""

    def __init__(
        self,
        batch_size: int = 3,
        keep_last_batches: int = 10,
        switch_confirm_batches: int = 3,
        degrade_confirm_batches: int = 5,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")
        if switch_confirm_batches <= 0 or degrade_confirm_batches <= 0:
            raise ValueError("几何切换确认批次数必须大于 0")
        self.batch_size = batch_size
        self.keep_last_batches = keep_last_batches
        self.switch_confirm_batches = switch_confirm_batches
        self.degrade_confirm_batches = degrade_confirm_batches
        self._batch: list[tuple[PageGeometry | None, bool]] = []
        self._last: PageGeometry | None = None
        self._stale_batches = 0
        self._pending: PageGeometry | None = None
        self._pending_batches = 0

    def reset(self) -> None:
        """清除跨帧状态；目标窗口失效或客户区尺寸改变时调用。"""

        self._batch.clear()
        self._last = None
        self._stale_batches = 0
        self._clear_pending()

    def push(
        self,
        geometry: PageGeometry | None,
        *,
        suppress: bool = False,
    ) -> tuple[bool, PageGeometry | None]:
        """加入一帧结果；suppress 表示该帧明确要求隐藏，而非普通识别丢失。"""

        self._batch.append((geometry, suppress))
        if len(self._batch) < self.batch_size:
            return False, None
        batch, self._batch = self._batch, []

        suppress_count = sum(1 for _geometry, should_suppress in batch if should_suppress)
        suppress_threshold = self.batch_size // 2 + 1
        if suppress_count >= suppress_threshold:
            self.reset()
            return True, None

        valid = [
            item
            for item, should_suppress in batch
            if item is not None and not should_suppress
        ]
        if not valid:
            self._clear_pending()
            self._stale_batches += 1
            if self._last is not None and self._stale_batches <= self.keep_last_batches:
                return True, self._last
            self._last = None
            return True, None

        groups: dict[tuple[object, ...], list[PageGeometry]] = defaultdict(list)
        for item in valid:
            groups[(item.mode, item.orientation, item.anchor_edge, item.draw_vertical, item.draw_horizontal)].append(item)
        selected = max(groups.values(), key=lambda group: (len(group), sum(item.confidence for item in group)))
        aggregated = self._aggregate(selected)

        if self._last is None:
            return self._accept(aggregated)
        return self._resolve_candidate(aggregated)

    def _resolve_candidate(self, candidate: PageGeometry) -> tuple[bool, PageGeometry | None]:
        assert self._last is not None
        previous = self._last
        previous_quality = self._quality(previous)
        candidate_quality = self._quality(candidate)

        if self._same_page_evidence(previous, candidate):
            # 同一页面从完整矩形暂时退化为两直角时，继续使用信息更完整的旧几何。
            if candidate_quality < previous_quality:
                self._clear_pending()
                self._stale_batches = 0
                return True, previous

            same_mode = (
                previous.mode,
                previous.orientation,
                previous.anchor_edge,
            ) == (
                candidate.mode,
                candidate.orientation,
                candidate.anchor_edge,
            )
            if same_mode:
                return self._accept(self._smooth(previous, candidate))
            if candidate_quality > previous_quality:
                return self._accept(candidate)

        required_batches = (
            self.degrade_confirm_batches
            if candidate_quality < previous_quality
            else self.switch_confirm_batches
        )
        return self._confirm_switch(candidate, required_batches)

    def _confirm_switch(
        self,
        candidate: PageGeometry,
        required_batches: int,
    ) -> tuple[bool, PageGeometry | None]:
        if self._pending is not None and self._same_candidate(self._pending, candidate):
            self._pending = self._smooth(self._pending, candidate)
            self._pending_batches += 1
        else:
            self._pending = candidate
            self._pending_batches = 1

        if self._pending_batches < required_batches:
            self._stale_batches = 0
            return True, self._last

        accepted = self._pending
        assert accepted is not None
        return self._accept(accepted)

    def _accept(self, geometry: PageGeometry) -> tuple[bool, PageGeometry]:
        self._last = geometry
        self._stale_batches = 0
        self._clear_pending()
        return True, geometry

    def _clear_pending(self) -> None:
        self._pending = None
        self._pending_batches = 0

    @staticmethod
    def _aggregate(items: list[PageGeometry]) -> PageGeometry:
        representative = max(items, key=lambda item: item.confidence)
        rect = RectF(
            float(median(item.rect.left for item in items)),
            float(median(item.rect.top for item in items)),
            float(median(item.rect.right for item in items)),
            float(median(item.rect.bottom for item in items)),
        )
        return replace(
            representative,
            rect=rect,
            confidence=float(sum(item.confidence for item in items) / len(items)),
            px_per_cm_x=float(median(item.px_per_cm_x for item in items)),
            px_per_cm_y=float(median(item.px_per_cm_y for item in items)),
        )

    @staticmethod
    def _quality(geometry: PageGeometry) -> int:
        if geometry.mode == "full":
            return 3
        if geometry.mode == "partial-diagonal":
            return 2
        return 1

    @classmethod
    def _same_candidate(cls, first: PageGeometry, second: PageGeometry) -> bool:
        if (first.mode, first.orientation, first.anchor_edge) != (
            second.mode,
            second.orientation,
            second.anchor_edge,
        ):
            return False
        return cls._same_page_evidence(first, second)

    @classmethod
    def _same_page_evidence(cls, first: PageGeometry, second: PageGeometry) -> bool:
        if first.orientation != second.orientation:
            return False
        tolerance = max(
            12.0,
            0.04 * max(first.rect.width, first.rect.height, second.rect.width, second.rect.height),
        )

        complete_modes = {"full", "partial-diagonal"}
        if first.mode in complete_modes and second.mode in complete_modes:
            return cls._rect_close(first.rect, second.rect, tolerance)

        if first.mode in complete_modes:
            return cls._partial_matches_complete(second, first, tolerance)
        if second.mode in complete_modes:
            return cls._partial_matches_complete(first, second, tolerance)

        if first.mode == second.mode == "partial-horizontal" and first.anchor_edge == second.anchor_edge:
            if first.anchor_edge == "top":
                values = (
                    abs(first.rect.left - second.rect.left),
                    abs(first.rect.right - second.rect.right),
                    abs(first.rect.top - second.rect.top),
                )
            else:
                values = (
                    abs(first.rect.left - second.rect.left),
                    abs(first.rect.right - second.rect.right),
                    abs(first.rect.bottom - second.rect.bottom),
                )
            return max(values) <= tolerance

        if first.mode == second.mode == "partial-vertical" and first.anchor_edge == second.anchor_edge:
            if first.anchor_edge == "left":
                values = (
                    abs(first.rect.top - second.rect.top),
                    abs(first.rect.bottom - second.rect.bottom),
                    abs(first.rect.left - second.rect.left),
                )
            else:
                values = (
                    abs(first.rect.top - second.rect.top),
                    abs(first.rect.bottom - second.rect.bottom),
                    abs(first.rect.right - second.rect.right),
                )
            return max(values) <= tolerance
        return False

    @staticmethod
    def _rect_close(first: RectF, second: RectF, tolerance: float) -> bool:
        return max(
            abs(first.left - second.left),
            abs(first.top - second.top),
            abs(first.right - second.right),
            abs(first.bottom - second.bottom),
        ) <= tolerance

    @staticmethod
    def _partial_matches_complete(
        partial: PageGeometry,
        complete: PageGeometry,
        tolerance: float,
    ) -> bool:
        if partial.mode == "partial-horizontal":
            edge_delta = (
                abs(partial.rect.top - complete.rect.top)
                if partial.anchor_edge == "top"
                else abs(partial.rect.bottom - complete.rect.bottom)
            )
            return max(
                abs(partial.rect.left - complete.rect.left),
                abs(partial.rect.right - complete.rect.right),
                edge_delta,
            ) <= tolerance
        if partial.mode == "partial-vertical":
            edge_delta = (
                abs(partial.rect.left - complete.rect.left)
                if partial.anchor_edge == "left"
                else abs(partial.rect.right - complete.rect.right)
            )
            return max(
                abs(partial.rect.top - complete.rect.top),
                abs(partial.rect.bottom - complete.rect.bottom),
                edge_delta,
            ) <= tolerance
        return False

    @staticmethod
    def _smooth(previous: PageGeometry, current: PageGeometry) -> PageGeometry:
        alpha = 0.55
        blend = lambda old, new: old * (1 - alpha) + new * alpha
        return replace(
            current,
            rect=RectF(
                blend(previous.rect.left, current.rect.left),
                blend(previous.rect.top, current.rect.top),
                blend(previous.rect.right, current.rect.right),
                blend(previous.rect.bottom, current.rect.bottom),
            ),
            px_per_cm_x=blend(previous.px_per_cm_x, current.px_per_cm_x),
            px_per_cm_y=blend(previous.px_per_cm_y, current.px_per_cm_y),
        )


def transform_geometry(
    geometry: PageGeometry,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    dx: float = 0.0,
    dy: float = 0.0,
) -> PageGeometry:
    """将检测坐标缩放并平移到叠加层使用的客户区物理像素坐标。"""

    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("几何缩放比例必须大于 0")
    return replace(
        geometry,
        rect=RectF(
            geometry.rect.left * scale_x + dx,
            geometry.rect.top * scale_y + dy,
            geometry.rect.right * scale_x + dx,
            geometry.rect.bottom * scale_y + dy,
        ),
        px_per_cm_x=geometry.px_per_cm_x * scale_x,
        px_per_cm_y=geometry.px_per_cm_y * scale_y,
        corners=tuple(
            (x * scale_x + dx, y * scale_y + dy, kind)
            for x, y, kind in geometry.corners
        ),
    )


def translate_geometry(geometry: PageGeometry, dx: float, dy: float) -> PageGeometry:
    return transform_geometry(geometry, dx=dx, dy=dy)


def grid_lines(
    geometry: PageGeometry,
    viewport_width: int,
    viewport_height: int,
    config: OverlayConfig,
) -> list[tuple[float, float, float, float, bool]]:
    """返回已裁剪的网格线；partial-horizontal 只保留横向边上的纵向分割，反之亦然。"""

    lines: list[tuple[float, float, float, float, bool]] = []
    rect = geometry.rect
    if geometry.draw_vertical:
        step = geometry.px_per_cm_x * config.grid_width_cm
        if step >= 2:
            y1, y2 = max(0.0, rect.top), min(float(viewport_height), rect.bottom)
            if y2 > y1:
                index = 1
                x = rect.left + step
                while x < rect.right - 0.5 and index <= 1000:
                    if 0 <= x <= viewport_width:
                        cm_position = index * config.grid_width_cm
                        major = _is_major(cm_position, config.major_every_cm)
                        lines.append((x, y1, x, y2, major))
                    index += 1
                    x = rect.left + index * step

    if geometry.draw_horizontal:
        step = geometry.px_per_cm_y * config.grid_height_cm
        if step >= 2:
            x1, x2 = max(0.0, rect.left), min(float(viewport_width), rect.right)
            if x2 > x1:
                index = 1
                y = rect.top + step
                while y < rect.bottom - 0.5 and index <= 1000:
                    if 0 <= y <= viewport_height:
                        cm_position = index * config.grid_height_cm
                        major = _is_major(cm_position, config.major_every_cm)
                        lines.append((x1, y, x2, y, major))
                    index += 1
                    y = rect.top + index * step
    return lines


def _is_major(position_cm: float, major_every_cm: float) -> bool:
    if major_every_cm <= 0:
        return False
    quotient = position_cm / major_every_cm
    return math.isclose(quotient, round(quotient), abs_tol=1e-6)


def annotate_detection(frame_bgr: np.ndarray, result: DetectionResult, config: OverlayConfig) -> np.ndarray:
    annotated = frame_bgr.copy()
    for segment in result.horizontal_segments:
        cv2.line(
            annotated,
            (int(segment.start), int(segment.coord)),
            (int(segment.end), int(segment.coord)),
            (0, 200, 255),
            1,
        )
    for segment in result.vertical_segments:
        cv2.line(
            annotated,
            (int(segment.coord), int(segment.start)),
            (int(segment.coord), int(segment.end)),
            (0, 255, 0),
            1,
        )
    for corner in result.corners:
        cv2.circle(annotated, (int(corner.x), int(corner.y)), 5, (255, 0, 0), 2)
        cv2.putText(
            annotated,
            corner.kind,
            (int(corner.x) + 4, int(corner.y) - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 0, 0),
            1,
            cv2.LINE_AA,
        )
    if result.geometry is not None:
        rect = result.geometry.rect
        cv2.rectangle(
            annotated,
            (int(rect.left), int(rect.top)),
            (int(rect.right), int(rect.bottom)),
            (0, 0, 255),
            2,
        )
        for x1, y1, x2, y2, major in grid_lines(result.geometry, frame_bgr.shape[1], frame_bgr.shape[0], config):
            cv2.line(
                annotated,
                (int(round(x1)), int(round(y1))),
                (int(round(x2)), int(round(y2))),
                (255, 200 if major else 120, 0),
                2 if major else 1,
            )
    return annotated

