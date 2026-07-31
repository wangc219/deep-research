# -*- coding: utf-8 -*-
"""弹窗验证机制 Demo：用于验证 medspider 的验证提醒弹窗是否可用。"""

import argparse

try:
    from verify_popup_notifier import VERIFY_URL_PREFIX, show_verify_popup
except ImportError:
    from .verify_popup_notifier import VERIFY_URL_PREFIX, show_verify_popup


def is_verify_url(url):
    """判断是否为验证页 URL。"""
    return (url or "").startswith(VERIFY_URL_PREFIX)


def run_demo(scene):
    """模拟 medspider 遇到验证页后的提醒流程。"""
    current_url = VERIFY_URL_PREFIX + "demo"

    print("=" * 60)
    print("验证页弹窗机制 Demo 已启动")
    print("每次仍处于验证页时，都会弹窗提醒你先去浏览器人工完成验证。")
    print("在终端输入 ok 可模拟验证通过并退出。")
    print("=" * 60)

    while is_verify_url(current_url):
        shown = show_verify_popup(scene=scene, verify_url=current_url)
        if shown:
            print("已触发弹窗提醒。")
        else:
            print("弹窗触发失败，仅显示终端提醒。")

        answer = input("完成验证后输入 ok 继续（直接回车表示仍未完成）: ").strip().lower()
        if answer == "ok":
            current_url = "https://www.cnki.net/"
        else:
            print("仍处于验证页，稍后会再次弹窗提醒。")

    print("验证通过，Demo 结束。")


def main():
    parser = argparse.ArgumentParser(description="CNKI 验证页弹窗提醒 Demo")
    parser.add_argument("--scene", type=str, default="Demo 场景", help="弹窗中的触发位置描述")
    args = parser.parse_args()
    run_demo(args.scene)


if __name__ == "__main__":
    main()
