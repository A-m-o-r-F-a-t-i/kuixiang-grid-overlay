from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OverlayConfig:
    """程序配置。纸张和网格尺寸均使用厘米。"""

    target_title_keywords: tuple[str, ...] = ("奎享雕刻",)

    # 默认使用 A4 纵向。切换纸张时只需要修改这四项。
    paper_width_cm: float = 21.0
    paper_height_cm: float = 29.7
    grid_width_cm: float = 1.0
    grid_height_cm: float = 1.0

    # portrait / landscape / auto。边框不完整时 auto 优先采用上面的原始方向。
    paper_orientation: str = "portrait"

    # 每帧检测一次，每累计 3 帧才提交一次叠加层更新。
    update_every_frames: int = 3
    capture_interval_ms: int = 100
    keep_last_geometry_batches: int = 10
    # 与上一稳定页面不一致的新几何必须跨多个三帧批次持续出现，避免瞬时误框跳位。
    geometry_switch_confirm_batches: int = 3
    # 从完整矩形降级为两直角结果需要更长确认；短时漏角继续使用完整网格。
    geometry_degrade_confirm_batches: int = 5

    # 品红色可能因缩放抗锯齿而变浅或变深，阈值同时约束色相和 RGB 通道差。
    magenta_min_channel_delta: int = 8
    magenta_min_saturation: int = 18
    magenta_min_value: int = 35

    # 叠加层外观。
    overlay_alpha: float = 0.48
    grid_color: str = "#00C8D7"
    major_grid_color: str = "#008894"
    grid_line_width: int = 1
    major_line_width: int = 2
    major_every_cm: float = 5.0
    transparent_color: str = "#010203"

    # 叠加层作为奎享雕刻的非置顶所有者窗口，可在分屏中持续显示并随目标一起被其他窗口遮挡。
    hide_when_target_inactive: bool = False
    # 输入法、截图或窗口管理器可能短暂改变前台窗口；延迟隐藏可避免网格闪烁。
    inactive_grace_ms: int = 1500

    # 诊断图像输出目录，相对于项目目录。
    debug_dir_name: str = "debug"
    log_dir_name: str = "logs"


CONFIG = OverlayConfig()
