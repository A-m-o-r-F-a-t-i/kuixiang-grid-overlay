# Kuixiang Grid Overlay

[English](README.en.md)

一个面向 Windows 的非官方半透明网格叠加工具。程序自动检测奎享雕刻画布中的品红色纸张边框，在目标窗口上绘制可穿透鼠标的厘米网格，不修改奎享雕刻、模板 JSON 或雕刻路径。

> 本项目是独立的社区工具，与奎享雕刻的开发者或发行方没有隶属、授权或背书关系。

## 功能

- 自动检测浅色、深色和抗锯齿后的品红色纸张边框。
- 默认绘制 `1 cm × 1 cm` 网格，纸张和分割尺寸可独立配置。
- 四个角或任意三个兼容直角可生成完整横纵网格。
- 两个同边直角仅保留该边可确定的单方向分割；两个对角直角可恢复完整矩形。
- 只有一个直角时隐藏网格，避免依据不足时误显示。
- 每累计三帧提交一次更新，并对页面切换、漏角和错误候选执行跨批次确认。
- 兼容 DPI 虚拟化、125%/150%/175% 等显示缩放及多显示器移动。
- 叠加窗口不抢焦点、鼠标穿透，不使用全局置顶。
- 提供诊断截图、日志、全局快捷键和 Windows 计划任务启动脚本。

## 系统要求

- Windows 10 或 Windows 11。
- Python 3.10 及以上版本，当前开发环境使用 Python 3.12。
- 奎享雕刻窗口标题默认需要包含 `奎享雕刻`；可在 `config.py` 中修改目标关键字。

## 安装

```powershell
git clone https://github.com/A-m-o-r-F-a-t-i/kuixiang-grid-overlay.git
cd kuixiang-grid-overlay

py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 运行

```powershell
.\run_overlay.bat
```

`run_overlay.bat` 会调用 `start_overlay.ps1`，注册并启动当前用户的交互式计划任务 `KuixiangGridOverlay`。该任务只用于按需启动，不会设置登录时自动运行。

停止程序：

```powershell
.\stop_overlay.ps1
```

移除计划任务：

```powershell
Unregister-ScheduledTask -TaskName KuixiangGridOverlay -Confirm:$false
```

## 配置

主要参数集中在 `config.py`：

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| `paper_width_cm` | `21.0` | 纸张宽度，单位为厘米 |
| `paper_height_cm` | `29.7` | 纸张高度，单位为厘米 |
| `grid_width_cm` | `1.0` | 横向分割间距，单位为厘米 |
| `grid_height_cm` | `1.0` | 纵向分割间距，单位为厘米 |
| `paper_orientation` | `"portrait"` | `portrait`、`landscape` 或 `auto` |
| `update_every_frames` | `3` | 累计多少帧后提交一次更新 |
| `capture_interval_ms` | `100` | 两次检测之间的间隔 |
| `overlay_alpha` | `0.48` | 叠加层整体透明度 |
| `major_every_cm` | `5.0` | 加粗主网格的厘米周期 |
| `target_title_keywords` | `("奎享雕刻",)` | 目标窗口标题关键字 |

也可通过命令行临时覆盖尺寸：

```powershell
.\.venv\Scripts\python.exe .\overlay.py `
  --paper-width 21 `
  --paper-height 29.7 `
  --grid-width 1 `
  --grid-height 1 `
  --orientation portrait
```

## 检测规则

| 有效直角 | 行为 |
| ---: | --- |
| 4 个 | 使用完整矩形绘制横纵网格 |
| 3 个 | 重建缺失的第四角，绘制完整横纵网格 |
| 2 个对角 | 由对角线恢复完整矩形 |
| 2 个同边 | 仅绘制该边能够确定的单方向分割 |
| 1 个 | 隐藏网格 |
| 0 个 | 短时保留上一次稳定结果，超出保留期后隐藏 |

检测器同时使用 HSV 色相、RGB 通道差、线段合并和直角组合。`PrintWindow` 返回逻辑像素时，程序会根据物理客户区尺寸换算纸张矩形、角点和每厘米像素值，避免高 DPI 显示器上的缩小与偏移。

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl + Alt + G` | 显示或隐藏网格 |
| `Ctrl + Alt + D` | 保存当前检测诊断图 |
| `Ctrl + Alt + Q` | 退出程序 |

诊断图默认写入 `debug/`，日志默认写入 `logs/`。这两个目录已加入 `.gitignore`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

一次性诊断当前窗口，不创建叠加层：

```powershell
.\.venv\Scripts\python.exe .\overlay.py --diagnose-once
```

## 项目结构

```text
config.py              配置项
detector.py            边框、角点、稳定器和网格几何
overlay.py             捕获循环、Tk 叠加层和命令行入口
windows_api.py         Win32 窗口、DPI、截图和快捷键封装
start_overlay.ps1      按需注册并启动交互式计划任务
stop_overlay.ps1       停止当前叠加进程
tests/                 检测、DPI 与 Win32 回归测试
```

## 限制

- 网格只用于屏幕辅助，不会写入模板、预览或雕刻路径。
- 自动检测依赖纸张边框接近品红色；主题或边框颜色变化时需要调整阈值。
- 当前实现只支持 Windows。
- 两个同边直角无法唯一确定完整矩形，因此只显示可可靠确定的单方向分割。

## 许可证

本项目采用 [MIT License](LICENSE)。
