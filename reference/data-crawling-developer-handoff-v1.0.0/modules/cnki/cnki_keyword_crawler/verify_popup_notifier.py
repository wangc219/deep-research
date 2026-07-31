# -*- coding: utf-8 -*-
"""验证页弹窗提醒工具。"""

VERIFY_URL_PREFIX = "https://bar.cnki.net/bar/verify/"


def _show_windows_popup(title, message):
    """使用 Windows 原生 MessageBox 弹窗。"""
    import ctypes

    mb_ok = 0x00000000
    mb_icon_warning = 0x00000030
    mb_set_foreground = 0x00010000
    mb_topmost = 0x00040000
    mb_system_modal = 0x00001000
    flags = mb_ok | mb_icon_warning | mb_set_foreground | mb_topmost | mb_system_modal
    ctypes.windll.user32.MessageBoxW(None, message, title, flags)


def _show_tk_popup(title, message):
    """跨平台兜底弹窗。"""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showwarning(title, message, parent=root)
    root.destroy()


def show_verify_popup(scene="当前页面", verify_url=""):
    """显示拼图验证弹窗，返回是否成功显示。"""
    title = "CNKI 拼图验证提醒"
    message = (
        f"检测到需要人工拼图验证。\n\n"
        f"触发位置: {scene}\n"
        f"验证地址: {verify_url or '未知'}\n\n"
        f"请在浏览器中完成验证，然后回到终端继续。"
    )

    try:
        _show_windows_popup(title, message)
        return True
    except Exception:
        pass

    try:
        _show_tk_popup(title, message)
        return True
    except Exception:
        return False
