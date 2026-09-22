from __future__ import annotations

import unittest

import cv2
import numpy as np

from config import OverlayConfig
from detector import (
    BorderDetector,
    PageGeometry,
    RectF,
    ThreeFrameStabilizer,
    grid_lines,
    transform_geometry,
)


class BorderDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = OverlayConfig(hide_when_target_inactive=False)
        self.detector = BorderDetector(self.config)

    @staticmethod
    def frame(color: tuple[int, int, int], partial: str | None = None) -> np.ndarray:
        image = np.full((900, 900, 3), 245, dtype=np.uint8)
        left, top, right, bottom = 180, 100, 600, 694
        if partial is None:
            cv2.rectangle(image, (left, top), (right, bottom), color, 3)
        elif partial == "top":
            cv2.line(image, (left, top), (right, top), color, 3)
            cv2.line(image, (left, top), (left, top + 180), color, 3)
            cv2.line(image, (right, top), (right, top + 180), color, 3)
        elif partial == "left":
            cv2.line(image, (left, top), (left, bottom), color, 3)
            cv2.line(image, (left, top), (left + 180, top), color, 3)
            cv2.line(image, (left, bottom), (left + 180, bottom), color, 3)
        elif partial == "single":
            cv2.line(image, (left, top), (left + 180, top), color, 3)
            cv2.line(image, (left, top), (left, top + 180), color, 3)
        elif partial == "missing_tl":
            cv2.line(image, (left + 60, top), (right, top), color, 3)
            cv2.line(image, (right, top), (right, bottom), color, 3)
            cv2.line(image, (left, bottom), (right, bottom), color, 3)
            cv2.line(image, (left, top + 60), (left, bottom), color, 3)
        elif partial == "missing_tr":
            cv2.line(image, (left, top), (right - 60, top), color, 3)
            cv2.line(image, (right, top + 60), (right, bottom), color, 3)
            cv2.line(image, (left, bottom), (right, bottom), color, 3)
            cv2.line(image, (left, top), (left, bottom), color, 3)
        elif partial == "missing_bl":
            cv2.line(image, (left, top), (right, top), color, 3)
            cv2.line(image, (right, top), (right, bottom), color, 3)
            cv2.line(image, (left + 60, bottom), (right, bottom), color, 3)
            cv2.line(image, (left, top), (left, bottom - 60), color, 3)
        elif partial == "missing_br":
            cv2.line(image, (left, top), (right, top), color, 3)
            cv2.line(image, (right, top), (right, bottom - 60), color, 3)
            cv2.line(image, (left, bottom), (right - 60, bottom), color, 3)
            cv2.line(image, (left, top), (left, bottom), color, 3)
        return image

    def test_full_rectangle_accepts_bright_pale_and_dark_magenta(self) -> None:
        for color in ((255, 0, 255), (255, 180, 255), (120, 10, 120)):
            with self.subTest(color=color):
                result = self.detector.detect(self.frame(color))
                self.assertIsNotNone(result.geometry)
                self.assertEqual(result.geometry.mode, "full")
                self.assertAlmostEqual(result.geometry.rect.left, 180, delta=8)
                self.assertAlmostEqual(result.geometry.rect.right, 600, delta=8)

    def test_two_top_corners_keep_horizontal_edge_divisions(self) -> None:
        result = self.detector.detect(self.frame((255, 80, 255), partial="top"))
        self.assertIsNotNone(result.geometry)
        self.assertEqual(result.geometry.mode, "partial-horizontal")
        self.assertEqual(result.geometry.anchor_edge, "top")
        self.assertTrue(result.geometry.draw_vertical)
        self.assertFalse(result.geometry.draw_horizontal)
        self.assertLessEqual(result.geometry.rect.height, 190)

    def test_two_left_corners_keep_vertical_edge_divisions(self) -> None:
        result = self.detector.detect(self.frame((150, 15, 150), partial="left"))
        self.assertIsNotNone(result.geometry)
        self.assertEqual(result.geometry.mode, "partial-vertical")
        self.assertEqual(result.geometry.anchor_edge, "left")
        self.assertFalse(result.geometry.draw_vertical)
        self.assertTrue(result.geometry.draw_horizontal)
        self.assertLessEqual(result.geometry.rect.width, 190)

    def test_one_corner_does_not_create_geometry(self) -> None:
        result = self.detector.detect(self.frame((255, 80, 255), partial="single"))
        self.assertIsNone(result.geometry)
        self.assertEqual(len(result.corners), 1)

    def test_three_corners_reconstruct_complete_grid(self) -> None:
        for missing in ("missing_tl", "missing_tr", "missing_bl", "missing_br"):
            with self.subTest(missing=missing):
                result = self.detector.detect(self.frame((255, 80, 255), partial=missing))
                self.assertIsNotNone(result.geometry)
                self.assertEqual(result.geometry.mode, "full")
                self.assertTrue(result.geometry.draw_vertical)
                self.assertTrue(result.geometry.draw_horizontal)
                self.assertEqual(len(result.geometry.corners), 3)
                self.assertAlmostEqual(result.geometry.rect.left, 180, delta=8)
                self.assertAlmostEqual(result.geometry.rect.top, 100, delta=8)
                self.assertAlmostEqual(result.geometry.rect.right, 600, delta=8)
                self.assertAlmostEqual(result.geometry.rect.bottom, 694, delta=8)

                lines = grid_lines(result.geometry, 900, 900, self.config)
                vertical = [line for line in lines if line[0] == line[2]]
                horizontal = [line for line in lines if line[1] == line[3]]
                self.assertEqual(len(vertical), 20)
                self.assertEqual(len(horizontal), 29)

    def test_stabilizer_updates_only_every_three_frames(self) -> None:
        geometry = PageGeometry(
            RectF(0, 0, 210, 297),
            "full",
            0.9,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        stabilizer = ThreeFrameStabilizer(batch_size=3)
        self.assertEqual(stabilizer.push(geometry), (False, None))
        self.assertEqual(stabilizer.push(geometry), (False, None))
        should_update, output = stabilizer.push(geometry)
        self.assertTrue(should_update)
        self.assertIsNotNone(output)
        self.assertEqual(stabilizer.push(geometry), (False, None))

    def test_single_corner_majority_clears_previous_geometry(self) -> None:
        geometry = PageGeometry(
            RectF(0, 0, 210, 297),
            "full",
            0.9,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        stabilizer = ThreeFrameStabilizer(batch_size=3)
        stabilizer.push(geometry)
        stabilizer.push(geometry)
        self.assertEqual(stabilizer.push(geometry), (True, geometry))

        self.assertEqual(stabilizer.push(None, suppress=True), (False, None))
        self.assertEqual(stabilizer.push(None, suppress=True), (False, None))
        self.assertEqual(stabilizer.push(None), (True, None))

        stabilizer.push(None)
        stabilizer.push(None)
        self.assertEqual(stabilizer.push(None), (True, None))

    def test_zero_corner_loss_still_keeps_last_geometry(self) -> None:
        geometry = PageGeometry(
            RectF(0, 0, 210, 297),
            "full",
            0.9,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        stabilizer = ThreeFrameStabilizer(batch_size=3)
        stabilizer.push(geometry)
        stabilizer.push(geometry)
        stabilizer.push(geometry)
        stabilizer.push(None)
        stabilizer.push(None)
        self.assertEqual(stabilizer.push(None), (True, geometry))

    def test_matching_partial_does_not_downgrade_full_geometry(self) -> None:
        full = PageGeometry(
            RectF(100, 100, 310, 397),
            "full",
            0.99,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        partial = PageGeometry(
            RectF(100, 100, 310, 240),
            "partial-horizontal",
            0.9,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            False,
            "top",
        )
        stabilizer = ThreeFrameStabilizer(batch_size=3)
        stabilizer.push(full)
        stabilizer.push(full)
        stabilizer.push(full)
        stabilizer.push(partial)
        stabilizer.push(partial)
        should_update, output = stabilizer.push(partial)
        self.assertTrue(should_update)
        self.assertEqual(output.mode, "full")
        self.assertEqual(output.rect, full.rect)

    def test_incompatible_page_requires_cross_batch_confirmation(self) -> None:
        original = PageGeometry(
            RectF(100, 100, 310, 397),
            "full",
            0.99,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        wrong = PageGeometry(
            RectF(420, 500, 630, 797),
            "full",
            0.99,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        stabilizer = ThreeFrameStabilizer(batch_size=3, switch_confirm_batches=3)
        stabilizer.push(original)
        stabilizer.push(original)
        stabilizer.push(original)

        for _batch in range(2):
            stabilizer.push(wrong)
            stabilizer.push(wrong)
            should_update, output = stabilizer.push(wrong)
            self.assertTrue(should_update)
            self.assertEqual(output.rect, original.rect)

        stabilizer.push(wrong)
        stabilizer.push(wrong)
        should_update, output = stabilizer.push(wrong)
        self.assertTrue(should_update)
        self.assertEqual(output.rect, wrong.rect)

    def test_reset_discards_stale_page_geometry(self) -> None:
        geometry = PageGeometry(
            RectF(0, 0, 210, 297),
            "full",
            0.9,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        stabilizer = ThreeFrameStabilizer(batch_size=3)
        stabilizer.push(geometry)
        stabilizer.push(geometry)
        stabilizer.push(geometry)
        stabilizer.reset()
        stabilizer.push(None)
        stabilizer.push(None)
        self.assertEqual(stabilizer.push(None), (True, None))

    def test_default_a4_grid_is_one_centimetre(self) -> None:
        geometry = PageGeometry(
            RectF(0, 0, 210, 297),
            "full",
            0.9,
            "portrait",
            21,
            29.7,
            10,
            10,
            True,
            True,
        )
        lines = grid_lines(geometry, 210, 297, self.config)
        vertical = [line for line in lines if line[0] == line[2]]
        horizontal = [line for line in lines if line[1] == line[3]]
        self.assertEqual(len(vertical), 20)
        self.assertEqual(len(horizontal), 29)
        self.assertAlmostEqual(vertical[0][0], 10)
        self.assertAlmostEqual(horizontal[0][1], 10)

    def test_geometry_maps_logical_capture_to_physical_client_pixels(self) -> None:
        geometry = PageGeometry(
            RectF(314, 93.5, 708, 654.5),
            "partial-vertical",
            0.9,
            "portrait",
            21,
            29.7,
            18.8888888889,
            18.8888888889,
            False,
            True,
            "right",
            ((708, 93.5, "TR"), (708, 654.5, "BR")),
        )

        mapped = transform_geometry(geometry, 1.75, 1.75)

        self.assertEqual(mapped.rect, RectF(549.5, 163.625, 1239.0, 1145.375))
        self.assertAlmostEqual(mapped.px_per_cm_x, 33.0555555556)
        self.assertAlmostEqual(mapped.px_per_cm_y, 33.0555555556)
        self.assertEqual(mapped.corners[0], (1239.0, 163.625, "TR"))


if __name__ == "__main__":
    unittest.main()

