from __future__ import annotations

import os
import tkinter as tk
import unittest

from windows_api import (
    GWL_EXSTYLE,
    GWLP_HWNDPARENT,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    calculate_capture_scale,
    configure_overlay_window,
    get_toplevel_hwnd,
    user32,
)


@unittest.skipUnless(os.name == "nt", "仅在 Windows 上验证 Tk 原生句柄")
class WindowsApiTests(unittest.TestCase):
    def test_capture_scale_matches_dpi_virtualized_client(self) -> None:
        scale_x, scale_y = calculate_capture_scale(1820, 1127, 1040, 644)
        self.assertAlmostEqual(scale_x, 1.75)
        self.assertAlmostEqual(scale_y, 1.75)

    def test_tk_child_resolves_to_toplevel_window(self) -> None:
        root = tk.Tk(className="KuixiangGridOverlayHandleTest")
        try:
            root.withdraw()
            root.overrideredirect(True)
            root.update_idletasks()
            child_hwnd = int(root.winfo_id())
            top_hwnd = get_toplevel_hwnd(child_hwnd)
            self.assertNotEqual(child_hwnd, top_hwnd)
            self.assertEqual(int(user32.GetAncestor(child_hwnd, 2)), top_hwnd)
        finally:
            root.destroy()

    def test_overlay_is_clickthrough_owned_and_not_globally_topmost(self) -> None:
        owner = tk.Tk(className="KuixiangGridOwnerTest")
        overlay = tk.Toplevel(owner, class_="KuixiangGridOverlayStyleTest")
        try:
            owner.withdraw()
            overlay.withdraw()
            owner.update_idletasks()
            overlay.update_idletasks()
            owner_hwnd = get_toplevel_hwnd(int(owner.winfo_id()))
            overlay_hwnd = get_toplevel_hwnd(int(overlay.winfo_id()))

            configure_overlay_window(overlay_hwnd, owner_hwnd)
            ex_style = int(user32.GetWindowLongPtrW(overlay_hwnd, GWL_EXSTYLE))

            self.assertTrue(ex_style & WS_EX_LAYERED)
            self.assertTrue(ex_style & WS_EX_TRANSPARENT)
            self.assertTrue(ex_style & WS_EX_TOOLWINDOW)
            self.assertTrue(ex_style & WS_EX_NOACTIVATE)
            self.assertFalse(ex_style & WS_EX_TOPMOST)
            self.assertEqual(
                int(user32.GetWindowLongPtrW(overlay_hwnd, GWLP_HWNDPARENT)),
                owner_hwnd,
            )
        finally:
            overlay.destroy()
            owner.destroy()


if __name__ == "__main__":
    unittest.main()
