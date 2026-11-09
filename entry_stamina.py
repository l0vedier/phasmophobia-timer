# -*- coding: utf-8 -*-
"""独立体力条工具入口 —— 打包成 stamina.exe(恐鬼症工具-体力条)。

只有体力条浮窗 + 自己的设置(归满键 / 大小 / 长度)和编辑模式;
没有计时器、没有计时器热键。配置 = stamina.ini。
"""
import timer

if __name__ == "__main__":
    timer.main("stamina")
