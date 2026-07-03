"""Flet build 入口 shim。

`flet build` 在 app path 根目录查找 main.py。
此文件转发到真正的入口 app/main.py（其顶层调用 ft.run）。
开发时也可直接 `python main.py` 启动。
"""
import os
import runpy

_here = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(os.path.join(_here, "app", "main.py"), run_name="__main__")
