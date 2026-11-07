# -*- coding: utf-8 -*-
"""电量托盘入口 —— 双击运行（pythonw，不弹黑窗）。

真正的逻辑在 tray_app.py；这个文件只是给桌面/启动文件夹一个更直观的入口。
"""

from __future__ import annotations

import sys

import tray_app

if __name__ == "__main__":
    sys.exit(tray_app.main())
