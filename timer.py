# -*- coding: utf-8 -*-
"""
恐鬼症(Phasmophobia)计时器

在原有功能基础上增加了:
  * 系统托盘常驻(不用再只能靠 F5 关闭)
  * 编辑模式(拖动移动窗口 / 滚轮调字号,右键退出)
  * config.ini 配置文件 + 热重载(改完不用重启,也不用重新打包)
  * 托盘菜单里可直接捕获新按键

计时手感、热键默认值、布局坐标全部与原版一致。
"""

import configparser
import ctypes
import os
import re
import shutil
import sys
import threading
import time
import tkinter as tk

from PIL import Image
import pystray
from pynput import keyboard
from pynput.keyboard import Key
from pynput.mouse import Listener as MouseListener

APP_TITLE = "Phasmophobia Timer"
CONFIG_FILENAME = "config.ini"
# 「恢复上次设置」的自动快照:1 号 = config.ini 旁边这个文件,2~5 号依次叫
# config.prev2.ini ~ config.prev5.ini(都在用户目录里)。每次"新的一段调整"
# 开始时五槽轮转,见 Config.save。这不是垃圾文件,别删。
CONFIG_PREV_FILENAME = "config.prev.ini"
# 快照槽位数(2026-10-14 晚用户要求「记忆功能增加上限至五」):1 号最新,
# 数字越大越老;「恢复上次设置」连点 = 一层层往回退,最多退到这里。
CONFIG_PREV_SLOTS = 5
# 多久没保存才算"新的一段调整"(秒)。连续调整(滚轮连滚几十下)期间不刷新快照,
# 整段调整只留一个还原点 —— 否则滚一下覆盖一次,「恢复」永远只退最后一步。
SNAPSHOT_GAP_S = 120.0
# config.ini **不放程序文件夹**了(2026-10-14 起):改放用户目录
# %APPDATA%\PhasmophobiaTimer\。程序文件夹从此是纯代码 —— 更新程序只换
# 文件夹,谁的字号和位置都不会被换掉(旧版就是栽在这上面)。
# 完整路径拼法 + 旧版配置的一次性迁移见 _resolve_config_path()。
APP_DATA_DIRNAME = "PhasmophobiaTimer"
ICON_FILENAME = "ghost_icon.ico"
# 使用说明。**放在 exe 旁边**(不是塞进 _internal),这样改了不用重新打包。
# ⚠️ 打包时别忘了把它拷进成品目录 —— 漏了菜单项就是个死键。
MANUAL_FILENAME = "使用说明.md"

# F2「偷看」的亮起时长(秒):计时中虚化着按 F2 脱离虚化看一眼,期间没再按 F2,
# 到点自动回灰。2026-10-15 用户定稿——现在只有偷看走这个倒计时;「等待左键」
# 是常亮的,不排倒计时。不另开配置键 —— 不打算进 config.ini。
DIM_TIMEOUT_S = 3.0

# 编辑模式下用来"关掉"透明色的哨兵颜色。
# 这个颜色窗口里根本不存在,所以没有任何像素会被穿透,
# 整个窗口变成实心可点区域 —— 否则背景全穿透,没有地方能按住拖动。
TRANSPARENT_DISABLED = "#010203"

# 字体族和配色固定成原版的,不再走配置文件,托盘菜单里也没有改的入口。
# 字号不在这里 —— 编辑模式滚轮仍然可以调,存在 config.ini 的 *_font_size 里。
#
# 字体拆成两个,因为一个字体干不了这两件事:
#   FONT_FAMILY        —— 三个计时器的大数字,内容只有 0-9 和冒号
#   FONT_FAMILY_STATUS —— 状态文字,内容是中文(等待左键 / 进攻 / 平静 / 已暂停)
#
# 这不是"挑两个好看的",是**必须拆**:Consolas 里一个 CJK 字形都没有,
# 状态文字一直是 Windows 的字体回退在画 —— 用四个数字字体去量「等待左键」,
# 宽度全是 136px 一模一样,因为压根没用到它们。拆开之后两边各自指名道姓,
# 不再靠系统猜,以后换数字字体也不会连带把状态文字一起动掉。
#
# FONT_FAMILY_STATUS 用的是**中文族名**:Tk 的字体表里只有本地化名,
# 写 "Microsoft YaHei" 虽然也能解析到同一个族,但表里查不到,不如写这个稳。
FONT_FAMILY = "Digital-7 Mono"
FONT_FAMILY_STATUS = "微软雅黑"
# ⚠️ Digital-7 Mono 只有一个字重,所以这里的 "bold" 由 GDI **合成** ——
# 把笔画横着多描几遍凑粗(外扩约 1/24 em,80 号下约 4~5px)。
# 数码管字体的段与段之间缝隙本来就窄,有被糊住的风险。
#
# 看着发糊就改成 "normal"(一行的事,用不着重新打包,跑源码即可对比)。
# 想要**真**粗体的数码管风格就换 LCDMono2 —— 它有 Light/Normal/Bold/Ultra
# 四个真字重(LCDM2L__/N__/B__/U__.TTF),bold 走真文件不合成。
FONT_WEIGHT = "bold"

# 状态文字控件的纵向内边距。Tk 的 Label 默认就是 1,这里**显式写出来** ——
# _relayout 算基线时要拿它参与计算,靠"默认值恰好是 1"太脆。
STATUS_PADY = 1

COLOR_BG = "#1A1A1A"          # 同时是"透明色",就是上面 TRANSPARENT_DISABLED 说的那个机制
COLOR_MAIN = "#888888"        # 主计时器 初始(程序刚启动、还没按过 F1)
COLOR_MAIN_ON = "#666666"     # 主计时器 启用(按 F1 后 active=True)
COLOR_MAIN_OFF = "#4ECDC4"    # 主计时器 停用(按 F1 后 active=False)
COLOR_SEC_ON = "#4ECDC4"
COLOR_SEC_OFF = "#888888"
# (原 COLOR_TIMER2 已删:它只喂第二计时器,2026-10-14 起第二计时器的颜色
#  由 _sec2_color() 按状态算(2026-10-15 定稿:空闲/等待左键常亮,计时中虚化,
#  F2 偷看=亮 3 秒后自动回灰),写死的常量接不上虚化逻辑。
#  别再加回来。)
# (原 COLOR_STATUS 已删,2026-10-14:状态文字不再单独配色,改跟第二计时器一起走
#  _sec2_color() —— 用户点名"文字保持蓝色看起来很丑,改成跟第二计时器同步";
#  虚化变灰时文字跟着一起灰。别再给状态文字单配颜色。)
COLOR_EDIT_BORDER = "#4ECDC4"

# 改键窗口的配色。独立于上面的主窗口配色 —— 那个窗口是**实心面板**,
# 没有"透明色"这回事,所以这里的底色可以比主窗口的 #1A1A1A 亮一点。
HK_BG = "#242424"          # 面板底色(同时也是无边框窗口的填充色)
HK_BORDER = "#3A3A3A"      # 1px 外框 + 分组之间的细线 + 键帽描边
HK_ROW_HOVER = "#2E2E2E"   # 鼠标悬停时那一行的底色
HK_CAP_BG = "#223333"      # 正在捕获按键的那一行
HK_TEXT = "#DDDDDD"
HK_DIM = "#808080"
HK_ACCENT = "#4ECDC4"      # 和主窗口同一个青
HK_WARN = "#FFB86C"
HK_CHIP_BG = "#1A1A1A"     # 键帽底色
HK_CHIP_TEXT = "#DDDDDD"
HK_CLOSE_HOVER = "#FF6B6B"

# pynput 里代表修饰键的 Key。注意 Key.shift 与 Key.shift_l 是同一个枚举成员,
# 但 Key.ctrl 与 Key.ctrl_l 不是,所以要逐个别名写开(不能写成一行逗号列表)。
MODIFIER_KEYS = {
    Key.ctrl: "CTRL", Key.ctrl_l: "CTRL", Key.ctrl_r: "CTRL",
    Key.alt: "ALT", Key.alt_l: "ALT", Key.alt_r: "ALT", Key.alt_gr: "ALT",
    Key.shift: "SHIFT", Key.shift_l: "SHIFT", Key.shift_r: "SHIFT",
}

HOTKEY_DESCRIPTIONS = [
    ("toggle_active", "启用 / 停用计时器"),
    ("reset_second", "第二计时器(等待左键 / 偷看)"),
    ("toggle_stopwatch_active", "启用 / 停用秒表"),
    ("pause_resume", "暂停 / 继续"),
    ("stopwatch_start", "启动秒表"),
    ("toggle_stopwatch_view", "切换主显示 / 秒表显示"),
    ("close", "关闭程序"),
    ("click_second", "启动第二计时器"),
    ("click_reset", "重置并重开主计时器"),
]

# 改键窗口里**显示**用的名字。存进 config.ini 的仍然是 MOUSE_LEFT 这种规范写法 ——
# 这只是给人看的,别拿它去匹配热键。
SPEC_DISPLAY = {
    "MOUSE_LEFT": "鼠标左键", "MOUSE_MIDDLE": "鼠标中键", "MOUSE_RIGHT": "鼠标右键",
    "MOUSE_X1": "鼠标侧键1", "MOUSE_X2": "鼠标侧键2",
}

# 改键窗口里按这几组排、按这个顺序排。**纯粹管显示** —— 热键本身靠 action 名认,
# 分组排错了不影响任何功能。
#
# ⚠️ 加了新热键要**两处都加**:HOTKEY_DESCRIPTIONS(功能表)和这里(显示分组)。
#    只加前者的话,那一项不会出现在窗口里 —— 但 config.ini 里照旧能改,
#    所以是个"看得见摸不着"的哑巴坑。_open_hotkey_window 里对漏网的有兜底。
HOTKEY_GROUPS = [
    ("计时器", ("toggle_active", "reset_second", "pause_resume")),
    ("秒表", ("toggle_stopwatch_active", "stopwatch_start", "toggle_stopwatch_view")),
    ("鼠标", ("click_second", "click_reset")),
    ("程序", ("close",)),
]

HOTKEY_LABELS = dict(HOTKEY_DESCRIPTIONS)

DEFAULTS = {
    "Display": {
        # 秒表**没有**自己的字号 —— 它和主计时器是同一个位置(R 键互斥切换),
        # 字号一旦能分开设,切过去就会突然变大或变小。所以这里只有一个 font_size。
        "font_size": "87",
        "timer2_font_size": "40",
        "status_font_size": "25",
        "opacity": "0.85",
        "window_x": "10",
        "window_y": "10",
        # (window_x_prev / window_y_prev 曾住这里,是单独的「恢复上次位置」的记忆 ——
        #  2026-10-14 晚并进「恢复上次设置」的整份快照后已删。老配置里残留的这两个
        #  键没人读,不用清理)
        "window_w": "400",
        "window_h": "300",
        "font_step": "4",
    },
    "Timer": {
        "main_max": "180",
        "stopwatch_max": "300",
        "phase_minutes": "2",
        "pause_text_hide_ms": "1000",
    },
    "Hotkeys": {
        "toggle_active": "F1",
        "reset_second": "F2",
        "toggle_stopwatch_active": "F3",
        "pause_resume": "SPACE",
        "stopwatch_start": "T",
        "toggle_stopwatch_view": "R",
        "close": "F5",
        # 鼠标键没有修饰键,写成一个不带 `+` 的基名 —— 见 base_mouse_name()
        "click_second": "MOUSE_LEFT",
        "click_reset": "MOUSE_RIGHT",
    },
}

CONFIG_HEADER = """\
; ============================================================
;  恐鬼症计时器 配置文件
; ------------------------------------------------------------
;  * 改完保存即刻生效,不用重启程序,也不用重新打包 exe
;  * 字号用「编辑模式滚轮」调,不透明度用托盘菜单调,改完都会写回这里
;  * 你在本文件里手写的注释不会被覆盖,会原样保留
; ============================================================

; 【Display】外观
;   字体族和配色已固定在代码里(timer.py 顶部的 FONT_* / COLOR_* 常量),
;   不在这里配置,托盘菜单里也没有改的入口。
;   数字和状态文字用的是两个不同的字体族:前者只有 0-9,后者要写中文。
;   背景色 #1A1A1A 同时是"透明色",该颜色的像素会被做成点击穿透,
;   所以游戏点击不受窗口影响。改它等于同时改窗口背景和对游戏的穿透行为。
;
;   font_size                    主计时器字号(秒表**共用**这个值,没有单独的字号)
;   timer2_font_size             第二计时器字号
;   status_font_size             状态文字字号
;   opacity                      窗口不透明度 0.0 - 1.0
;   window_x / window_y          窗口位置(编辑模式拖动后自动写回)
;   window_w / window_h          窗口最小尺寸,内容变大会自动撑开
;   font_step                    编辑模式下滚轮每格调整的字号

; 【Timer】计时参数
;   main_max                     主计时器上限(秒),到点归零
;   stopwatch_max                独立秒表上限(秒)
;   phase_minutes                进攻 / 平静 单个相位时长(分钟)
;                                恐鬼症不同难度周期不同,在这里改
;   pause_text_hide_ms           "已暂停"字样显示多久后自动隐藏(毫秒)
;                                注:第二计时器「偷看」(计时中按 F2)只亮 3 秒,
;                                到点自动回灰 —— 那是代码常量 DIM_TIMEOUT_S,
;                                和本项无关;「等待左键」状态则常亮不限时

; 【Hotkeys】热键
;   写法:单个键写 F1 / SPACE / T
;         组合键写 CTRL+T / ALT+F1 / CTRL+SHIFT+R
;         鼠标键写 MOUSE_LEFT / MOUSE_RIGHT / MOUSE_MIDDLE / MOUSE_X1 / MOUSE_X2
;   留空表示不绑定该功能
"""


# ----------------------------------------------------------------------
# 路径 / 杂项工具
# ----------------------------------------------------------------------
def _app_dir():
    """exe / 脚本所在目录 —— 程序本体和随包资源放这里(配置**不**在这,见下)。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _config_dir():
    """配置文件所在的用户目录(%APPDATA%\\PhasmophobiaTimer)。

    配置以前放程序旁边 —— 更新程序要整个换文件夹,配置必然受牵连(不同用户的
    字号、位置各不相同,2026-10-14 用户点破的问题)。搬到用户目录后:
    更新 = 只换程序文件夹,配置永远不被动;发出去的任何一份第一次运行生成
    默认值,以后更新设置照旧;换电脑搬设置 = 拷这一个文件。
    """
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, APP_DATA_DIRNAME)


def _resolve_config_path():
    """定下配置文件的最终路径,顺带做旧位置的一次性迁移。

    用户目录没有配置、程序旁边有(旧版遗留的 config.ini)时:复制过去用,
    旧文件改名 config.ini.old **留着不删** —— 以后删了用户目录里的配置想
    重置时,它不会再把旧设置引回来(文件名已经不是 config.ini 了)。
    用户拿新版直接覆盖旧文件夹的场景,首次启动就把旁边旧配置接走,设置不丢。

    ⚠️ 用户目录万一写不进去(极罕见),退回"程序旁边"的老位置,保证程序能跑。
    ⚠️ 测试脚本通过改掉 _config_dir 来隔离配置(见 timer2-dim-test)。
    返回 (路径, 是否发生了迁移)。
    """
    path = os.path.join(_config_dir(), CONFIG_FILENAME)
    if not os.path.exists(path):
        try:
            os.makedirs(_config_dir(), exist_ok=True)
        except OSError:
            return os.path.join(_app_dir(), CONFIG_FILENAME), False
        legacy = os.path.join(_app_dir(), CONFIG_FILENAME)
        if os.path.exists(legacy):
            try:
                shutil.copyfile(legacy, path)
            except OSError:
                return legacy, False
            try:
                os.replace(legacy, legacy + ".old")
            except OSError:
                pass
            return path, True
    return path, False


def _prev_slot_path(config_path, i):
    """第 i 号自动快照的路径(1 = 最新,CONFIG_PREV_SLOTS = 最老)。

    1 号沿用老名字 config.prev.ini —— 老用户的单份快照无缝变成 1 号,不用迁移;
    2~5 号依次是 config.prev2.ini ~ config.prev5.ini,都和 config.ini 同目录。
    """
    d = os.path.dirname(config_path)
    if i == 1:
        return os.path.join(d, CONFIG_PREV_FILENAME)
    return os.path.join(d, "config.prev{}.ini".format(i))


def _resource_path(name):
    """打包后优先从 _MEIPASS 找随包资源,否则从脚本目录找。"""
    base = getattr(sys, "_MEIPASS", _app_dir())
    for d in (base, _app_dir()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return os.path.join(_app_dir(), name)


def _quote_args(args):
    return " ".join('"{}"'.format(a) if " " in a else a for a in args)


def _fmt_geometry(w, h, x, y):
    return "{}x{}+{}+{}".format(w, h, x, y)


def _chip_font(text):
    """键帽用哪个字体:纯 ASCII 用等宽,出现中文就换雅黑。

    键帽内容是两种东西:`CTRL+SHIFT+R` 这种是 ASCII,`鼠标左键` / `(未绑定)`
    是中文。Consolas 里一个 CJK 字形都没有,混排时中文是 Windows 字体回退
    在画 —— 和主窗口把数字 / 状态文字拆成两个字体族是同一个理由。
    """
    return ("Consolas", 10, "bold") if text.isascii() else (FONT_FAMILY_STATUS, 9)


def _ensure_admin():
    """非管理员则以管理员身份重启自己。

    原版这里直接 " ".join(sys.argv) 有两处毛病:把 argv[0](程序自身路径)
    也塞进了参数里,且带空格的路径会被拆成两个参数。这里一并修掉。
    """
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return

    if getattr(sys, "frozen", False):
        exe, params = sys.executable, _quote_args(sys.argv[1:])
    else:
        exe, params = sys.executable, _quote_args(sys.argv)
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    except Exception:
        pass
    sys.exit()


def _set_timer_precision(hi_res):
    """切换本进程的等待精度:True = 1ms,False = 系统默认(15.6ms)。

    ⚠️ 这是整个计时器延迟的**地板**。Windows 默认定时器一跳 15.6ms,
    tkinter 的 after() 醒不了比这更准 —— 秒边界对齐得再准,刷屏落点也是
    "边界后 0~15.6ms"。调成 1ms 之后收敛到 1~3ms。

    Win10 2004 起这个设定是**按进程**生效的,不会拖累别的程序;
    但也正因为按进程生效,必须由我们自己调,不能指望别的软件调过就万事大吉。
    """
    try:
        fn = ctypes.windll.winmm.timeBeginPeriod if hi_res else ctypes.windll.winmm.timeEndPeriod
        fn(1)
    except Exception:
        pass


# ----------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------
class Config(object):
    """config.ini 的读写。

    保存时做的是"逐行合并"而不是整体重写,所以你手写的注释和排列顺序
    都会保留;程序新增的键会补到对应节的末尾。
    """

    def __init__(self, path):
        self.path = path
        self.parser = configparser.ConfigParser()
        self.mtime = 0.0
        # 快照刚建立时调一下(托盘「恢复上次设置」要从灰变亮),由主程序挂上
        self.snapshot_hook = None
        # 「恢复上次设置」退回后置上:下一次保存先留快照再写 —— 退回的状态
        # 立刻成为新的还原点,免得"退回后再动手改"把历史挤乱(见 _restore_settings)
        self.pending_snapshot = False
        # 「恢复上次设置」已经退到第几层(0 = 还在"现在"),连点逐层回退靠它定位;
        # 任何保存都清零(动过手 = 回到现在,下次重新从 1 号退起)。⚠️ 别改成拿
        # config 字节和快照比对来"猜"层数 —— 当前内容可能恰好和某份**更老**的
        # 快照逐字节相同(如重置回默认位置,恰是同段起点),会以为"已经退到那层"
        # 而跳过更新的快照(2026-10-14 写测试时实际踩到,pos 用例直接挂)
        self.restore_depth = 0
        self.load()
        # 首次运行就把文件落盘,否则你根本找不到 config.ini 去手改
        if not os.path.exists(self.path):
            self.save()

    # ---------- 读 ----------
    def load(self):
        self.parser = configparser.ConfigParser()
        if os.path.exists(self.path):
            try:
                self.parser.read(self.path, encoding="utf-8")
            except configparser.Error:
                # 文件被改坏了:退回默认值,但不覆盖用户的文件,让他自己能看见
                self.parser = configparser.ConfigParser()

        # 补齐缺失的节和键(便于旧配置升级)
        for sec, kv in DEFAULTS.items():
            if not self.parser.has_section(sec):
                self.parser.add_section(sec)
            for key, val in kv.items():
                if not self.parser.has_option(sec, key):
                    self.parser.set(sec, key, val)

        self.mtime = self._disk_mtime()

    def _disk_mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def changed_on_disk(self):
        return self._disk_mtime() > self.mtime + 1e-6

    # ---------- 取值 ----------
    def get(self, sec, key):
        try:
            return self.parser.get(sec, key).strip()
        except (configparser.Error, KeyError):
            return DEFAULTS[sec][key]

    def get_int(self, sec, key):
        try:
            return int(float(self.get(sec, key)))
        except (TypeError, ValueError):
            return int(DEFAULTS[sec][key])

    def get_float(self, sec, key):
        try:
            return float(self.get(sec, key))
        except (TypeError, ValueError):
            return float(DEFAULTS[sec][key])

    # ---------- 写 ----------
    def set(self, sec, key, value):
        if not self.parser.has_section(sec):
            self.parser.add_section(sec)
        self.parser.set(sec, key, str(value))

    def save(self, force_snapshot=False):
        # —— 自动快照(托盘「恢复上次设置」的还原点,CONFIG_PREV_SLOTS 个槽位)——
        # 只在"新的一段调整"开始时刷新:距上次保存 ≥ SNAPSHOT_GAP_S 才动,
        # 连续调整期间快照一直停在这一段开始前(滚轮连滚几十下也只算一段)。
        # 刷新 = 五槽轮转:5 号(最老)删掉,4→5、3→4、2→3、1→2,再把保存前的
        # 整份配置补进 1 号 —— 「恢复上次设置」因此能一层层往回退(见
        # _restore_settings)。force_snapshot / pending_snapshot = 不管间隔,
        # 先刷再写(「重置窗口位置」和"退回后再动手改"的第一次保存,见那两处)。
        # ⚠️ "上次保存时刻"直接用 config.ini 的 mtime,别另存状态变量 ——
        #    重启、外部改了文件之后照样对。
        force = force_snapshot or self.pending_snapshot
        self.pending_snapshot = False
        self.restore_depth = 0      # 动过手保存 = 回到"现在",「恢复」下次从 1 号退起
        try:
            if os.path.exists(self.path):
                s1 = _prev_slot_path(self.path, 1)
                created = not os.path.exists(s1)
                if (created or force
                        or time.time() - os.path.getmtime(self.path) >= SNAPSHOT_GAP_S):
                    # 轮转:最老的删掉,其余往后挪一格,给"保存前"腾出 1 号
                    oldest = _prev_slot_path(self.path, CONFIG_PREV_SLOTS)
                    if os.path.exists(oldest):
                        os.remove(oldest)
                    for i in range(CONFIG_PREV_SLOTS - 1, 0, -1):
                        src = _prev_slot_path(self.path, i)
                        if os.path.exists(src):
                            os.replace(src, _prev_slot_path(self.path, i + 1))
                    shutil.copyfile(self.path, s1)
                    if created and self.snapshot_hook:
                        self.snapshot_hook()
        except OSError:
            pass

        lines = []
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError:
                lines = []

        head, sections, order = [], {}, []
        cur = None
        for line in lines:
            st = line.strip()
            if st.startswith("[") and st.endswith("]") and st.count("[") == 1:
                cur = st[1:-1]
                if cur not in sections:
                    sections[cur] = []
                    order.append(cur)
                continue
            if cur is None:
                head.append(line)
            else:
                sections[cur].append(line)

        if not head:
            head = CONFIG_HEADER.splitlines()

        # 去掉尾部空行。否则每保存一次,上一节的分隔空行就会被当成正文
        # 吸收进来、再补一层新的,空行越滚越多。
        while head and not head[-1].strip():
            head.pop()
        for body in sections.values():
            while body and not body[-1].strip():
                body.pop()

        out = list(head)
        for sec in order + [s for s in self.parser.sections() if s not in sections]:
            out.append("")
            out.append("[{}]".format(sec))
            written = set()
            for line in sections.get(sec, []):
                st = line.strip()
                if st and not st.startswith(("#", ";")) and "=" in st:
                    key = st.split("=", 1)[0].strip()
                    if self.parser.has_option(sec, key):
                        out.append("{} = {}".format(key, self.parser.get(sec, key)))
                        written.add(key)
                        continue
                out.append(line)
            for key in self.parser.options(sec):
                if key not in written:
                    out.append("{} = {}".format(key, self.parser.get(sec, key)))

        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(out).rstrip() + "\n")
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
        self.mtime = self._disk_mtime()


# ----------------------------------------------------------------------
# 按键名 <-> 字符串
# ----------------------------------------------------------------------
def base_key_name(key):
    """把一个 pynput 按键对象转成名字:'F1' / 'SPACE' / 'T' / None。"""
    if isinstance(key, Key):
        name = getattr(key, "name", None)
        return name.upper() if name else None
    ch = getattr(key, "char", None)
    if isinstance(ch, str) and len(ch) == 1 and ch.isascii() and ch.isprintable():
        return ch.upper()
    return None


def base_mouse_name(button):
    """把一个 pynput 鼠标键转成名字:'MOUSE_LEFT' / 'MOUSE_RIGHT' / ... / None。

    ⚠️ 这个名字是**故意**选成没有 `+` 的 —— 这样 spec_to_parts() 和 match_hotkey()
    **一行都不用改**就能处理鼠标键:`spec_to_parts("MOUSE_LEFT")` 得到
    `(frozenset(), "MOUSE_LEFT")`,和 `"SPACE"` 走的是同一条路。
    存进 config.ini 的也是这个字符串。
    """
    name = getattr(button, "name", None)
    if not name:
        return None
    return "MOUSE_" + name.upper()


def spec_to_parts(spec):
    """'CTRL+SHIFT+R' -> (frozenset({'CTRL','SHIFT'}), 'R')"""
    parts = [p.strip().upper() for p in (spec or "").split("+") if p.strip()]
    if not parts:
        return frozenset(), None
    return frozenset(parts[:-1]), parts[-1]


# 匹配热键时当成"透明"的修饰键。
# 游戏里 SHIFT 基本等于"按住跑动",它和热键总是同时按着 —— 不放行的话,
# Shift+W 跑动时按 F2 会完全没反应(旧的精确匹配就是这么挂的)。
# CTRL / ALT 故意不放行:它们参与系统快捷键(Ctrl+T 新标签页 / Alt+F4 关窗),
# 放行会让程序在你用浏览器时乱触发。
TRANSPARENT_MODS = ("SHIFT",)


def match_hotkey(hotkeys, name, mods):
    """按键名 + 当前按住的修饰键集合,判断该触发哪个动作;没有就返回 None。

    分两轮找,顺序不能反:
      1. 精确匹配 —— 绑了组合键就优先认组合键,CTRL+SHIFT+R 这类才不会被裸键抢走。
      2. 把 TRANSPARENT_MODS 去掉后再匹配一次 —— 专治"按住 Shift 就没反应"。
    """
    for action, (want_mods, want_base) in hotkeys.items():
        if want_base == name and want_mods == mods:
            return action
    soft = frozenset(m for m in mods if m not in TRANSPARENT_MODS)
    for action, (want_mods, want_base) in hotkeys.items():
        if want_base == name and want_mods == soft:
            return action
    return None


# ----------------------------------------------------------------------
# 主程序
# ----------------------------------------------------------------------
class SimpleGameTimer(object):

    def __init__(self):
        # 配置住用户目录(与程序文件夹分离);旧版放在程序旁边的会被接过来一次
        cfg_path, self._config_migrated = _resolve_config_path()
        self.cfg = Config(cfg_path)

        # ---- 运行状态 ----
        self.active = True
        self.state = "stopped"
        self.start_time = 0.0
        self.elapsed_time = 0.0
        self.pause_hide_after_id = None
        self.force_hide_pause_text = False

        self.state2 = "stopped"
        self.start_time2 = 0.0
        # 「等待左键」= 常亮等左键起表的状态。2026-10-15 定稿:没有时限,
        # 进等待就一直亮着,点左键才起表(见 handle_f2_key)。
        self.timer2_waiting = False
        # 等待左键期间左键能不能起表。与 timer2_waiting 同步置位/清零。
        self.timer2_armed = False
        # 显示是不是虚化(灰)。2026-10-15 用户定稿:**初始就常亮**(不再一开机
        # 就是灰的);空闲/等待左键常亮;点左键起表**立刻**变灰,计时中一直灰;
        # F2 偷看临时亮 3 秒,期间再按 F2 进等待(又常亮)。见 _sec2_color。
        self.timer2_dimmed = False
        self._timer2_dim_id = None   # 偷看 3 秒倒计时的 after id(见 _schedule_dim_timer2)
        self.last_min2 = -1
        self._phase_text = ""

        self.new_sec_running = False
        self.new_start_sec = 0.0
        self.show_sec_mode = False
        self.sec_active = True

        # ---- 交互状态 ----
        self.edit_mode = False
        self.bg_color = COLOR_BG
        self._pos = (0, 0)
        self._drag_offset = None
        self._pressed_mods = set()
        self._held_keys = set()
        self._capturing = None
        self._capture_deadline = 0.0
        self._tick_id = None
        self._hi_res = False      # 本进程是否已提到 1ms 定时器精度
        self._tray = None
        # 按过 F1 之前显示初始色(原版行为),按过之后才在启用/停用两色间切换
        self._main_color_touched = False
        self._hotkey_win = None
        self._hotkey_rows = {}     # action -> 该行的一堆控件(改键窗口关掉即清空)
        self._hotkey_hint = None
        # 参数行(透明度/字号/上限)。窗口没开过时也为空字典 ——
        # 编辑模式滚轮调透明度会在窗口未开时走 _refresh_tweak_values,
        # 之前只在 _open_hotkey_window 里创建,首次滚轮直接 AttributeError(exe 无控制台,静默)。
        self._tw = {}
        self._tw_file = None

        # ---- 计时参数(从配置读,热重载时刷新) ----
        self._load_timer_params()
        self.hotkeys = self._load_hotkeys()

        self._build_window()
        self._apply_style()
        self._relayout()          # 末尾会调 _apply_view_mode,主显示区在那里摆

        self._start_tray()
        # 快照建立时要刷托盘菜单(「恢复上次设置」从灰变亮),见 Config.save
        self.cfg.snapshot_hook = self._refresh_tray
        self._start_listeners()

        self.root.protocol("WM_DELETE_WINDOW", self.close_program)
        self._tick()

        # 旧版配置刚从程序旁边搬过来 —— 状态栏提一句。和 _open_manual 的
        # "没找到 使用说明.md" 同款:_tick 每秒会刷新状态栏,实际只亮 ~1 秒,
        # after 只是兜底收尾,别指望它把提示按住。
        if self._config_migrated:
            self.status_label.config(text="设置已迁移到新位置")
            self.root.after(2500, self._update_status_label)

    # ==================================================================
    # 配置
    # ==================================================================
    def _load_timer_params(self):
        self.main_max = self.cfg.get_int("Timer", "main_max")
        self.stopwatch_max = self.cfg.get_int("Timer", "stopwatch_max")
        self.phase_minutes = max(1, self.cfg.get_int("Timer", "phase_minutes"))
        self.pause_hide_ms = self.cfg.get_int("Timer", "pause_text_hide_ms")

    def _load_hotkeys(self):
        table = {}
        for action, _label in HOTKEY_DESCRIPTIONS:
            mods, base = spec_to_parts(self.cfg.get("Hotkeys", action))
            if base:
                table[action] = (mods, base)
        return table

    def _reload_from_disk(self):
        """外部改动了 config.ini —— 重新读取并应用到界面。"""
        was_editing = self.edit_mode
        if was_editing:
            # 重载过程中样式会重建,先退出编辑模式避免状态错乱
            self._exit_edit_mode(save=False)

        self.cfg.load()
        self._load_timer_params()
        self.hotkeys = self._load_hotkeys()
        # 改键窗口开着时,外部手改 config.ini 也要跟着刷键帽(窗口没开时是空操作)
        self._refresh_hotkey_list()
        self._apply_style()

        # 位置也跟配置走(手动改了 window_x / window_y 就立刻生效)
        self._pos = (self.cfg.get_int("Display", "window_x"),
                     self.cfg.get_int("Display", "window_y"))
        self._relayout()          # 末尾会调 _apply_view_mode,主显示区在那里摆

        if was_editing:
            self._enter_edit_mode()

    def _open_config(self):
        try:
            os.startfile(self.cfg.path)
        except Exception:
            pass

    def _open_manual(self):
        """打开使用说明。

        用 _resource_path 而不是直接拼 _app_dir():它先找 _MEIPASS 再找 exe 目录,
        文档放哪一层都能找到 —— 和托盘图标一个路子(见 _start_tray)。
        找不到时在状态栏闪一句。**不能静默返回** —— 点了菜单什么都没发生,
        用的人只会以为程序坏了,而真正的原因是打包时漏拷了文档。
        """
        path = _resource_path(MANUAL_FILENAME)
        if not os.path.exists(path):
            self.status_label.config(text="没找到 " + MANUAL_FILENAME)
            self.root.after(1500, self._update_status_label)
            return
        try:
            os.startfile(path)
        except Exception:
            pass

    # ==================================================================
    # 窗口与样式
    # ==================================================================
    def _build_window(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)

        self._pos = (self.cfg.get_int("Display", "window_x"),
                     self.cfg.get_int("Display", "window_y"))
        self.root.geometry(_fmt_geometry(self.cfg.get_int("Display", "window_w"),
                                         self.cfg.get_int("Display", "window_h"),
                                         self._pos[0], self._pos[1]))

        try:
            icon = _resource_path(ICON_FILENAME)
            if os.path.exists(icon):
                self.root.iconbitmap(icon)
        except Exception:
            pass

        # 主计时器
        self.time_label = tk.Label(
            self.root, text="00:00", font=(FONT_FAMILY, 87, FONT_WEIGHT),
            fg="#888888", bg="#1A1A1A", bd=1, relief="flat", padx=10, pady=0)
        self.time_label.place(x=20, y=20)

        # 独立秒表。它和主计时器互斥显示(R 键切换),右边缘与主计时器对齐
        # ——bd/padx 必须和主计时器一样,墨迹边缘才落在同一个 x+bd+padx。
        # anchor 用 E:写字靠右,配合 _apply_view_mode 里 place 的 anchor="ne"。
        self.sec_label = tk.Label(
            self.root, text="00", font=(FONT_FAMILY, 87, FONT_WEIGHT),
            fg="#4ECDC4", bg="#1A1A1A", bd=1, relief="flat", padx=10, pady=0,
            anchor=tk.E)
        self.sec_label.place(x=20, y=20, anchor="nw")
        self.sec_label.place_forget()

        # 状态文字
        self.status_label = tk.Label(
            self.root, text="", font=(FONT_FAMILY_STATUS, 25, FONT_WEIGHT),
            fg="#4ECDC4", bg="#1A1A1A", bd=1, relief="flat", pady=STATUS_PADY)

        # 第二个计时器
        # bd 和 padx 必须和主计时器一模一样:文字墨迹的起点是 x + bd + padx,
        # 这两项不同,两个计时器的左边就对不齐(之前差 6px)。
        self.time_label2 = tk.Label(
            self.root, text="00:00", font=(FONT_FAMILY, 40, FONT_WEIGHT),
            fg="#4ECDC4", bg="#1A1A1A", bd=1, relief="flat", padx=10, pady=0)

        # 编辑模式用的边框和提示(默认不显示)
        self.edit_border = tk.Frame(self.root, bg="#1A1A1A",
                                    highlightthickness=3, highlightbackground="#4ECDC4")
        self.edit_hint = tk.Label(self.root, text="", font=("Microsoft YaHei", 10),
                                  fg="#4ECDC4", bg="#1A1A1A")

    # 状态文字可能出现的内容。给第二计时器定位时取其中最宽的一个,
    # 这样状态内容来回切换时它不会左右跳。
    #
    # ⚠️「进攻」「平静」前面垫的是**全角空格 U+3000**,不是普通空格。
    # 这两个词只有两个字,而「等待左键」有四个 —— 都从左边缘起画的话,
    # 短的会贴在左边,和「等待左键」不在一个视觉位置上。
    # 全角空格实测正好 33px = 一个汉字的宽度(和「等」等宽),垫上去它们就
    # 落在「待左」那两个字底下了。普通半角空格只有 10px,对不齐。
    PHASE_ATTACK = "　进攻"
    PHASE_CALM = "　平静"
    STATUS_TEXTS = ("", "已 暂 停", "等待左键", PHASE_ATTACK, PHASE_CALM)

    def _status_reserved_width(self):
        """状态栏按最宽内容预留的宽度。用临时控件实测,不同字体族才准。"""
        probe = tk.Label(self.root, text="", bd=1, font=(
            FONT_FAMILY_STATUS, self.cfg.get_int("Display", "status_font_size"), FONT_WEIGHT))
        widest = 0
        for txt in self.STATUS_TEXTS:
            probe.config(text=txt)
            probe.update_idletasks()
            widest = max(widest, probe.winfo_reqwidth())
        probe.destroy()
        return widest

    def _relayout(self):
        """按当前字号重新摆放控件,并保证窗口足够大。"""
        self.root.update_idletasks()

        # ⚠️ winfo_reqheight() 是"从 y=0 量"的高度,而主计时器摆在 y=20 ——
        # 算下边缘必须加上它自己的 y,否则第二计时器会往上蹿 20px 压在主计时器上。
        #
        # 旧代码是 `t2_y = t1_h + distance_below - 10`,两个毛病叠在一起:
        #   1) 那个 `-10` 正好把 distance_below 抵消掉,本该留的间隙没了;
        #   2) 漏了主计时器的 y=20。
        # 结果两个控件的框**永远重叠 20px,跟字号多大无关** ——
        # 换字体后 LCDMono2 的行高比 Consolas 紧,墨迹就把这个重叠露出来了。
        main_y = self.time_label.winfo_y()
        t1_h = self.time_label.winfo_reqheight()
        # 0 = 两个控件的框**刚好贴住**,再往上就会重叠。
        # 主计时器的墨迹离框底还有 22px(Digital-7 Mono 行框留白大),
        # 所以贴住之后两段墨迹之间仍有 34px 的空隙,看着不挤。
        distance_below = 0

        # 第二计时器:接在主计时器的**下边缘**下面,左边缘与它对齐(都在 x=20)
        t2_y = main_y + t1_h + distance_below
        self.time_label2.place(x=20, y=t2_y)
        self.root.update_idletasks()

        # 状态文字摆到第二计时器的右边。x 是定值,不随文字内容左右跳。
        status_x = 20 + self.time_label2.winfo_reqwidth() + 12

        # y 要让两者的**墨迹底边齐平**。
        #
        # ⚠️ 不能对**控件框** —— 两个控件字体不同、字号也不同,框对齐了墨迹照样歪。
        # 只能对**基线**,基线在各自控件内的偏移 = bd + pady + ascent。
        # 两边 bd 都是 1,抵消掉,只剩状态文字多出来的那个 pady。
        #
        # 但基线和**墨迹底边**之间还有一点差,而且两个字体差的方向**相反**(实测):
        #     微软雅黑        汉字略微**探到基线下**   约 0.12  × 字号(25 号 3px、40 号 5px)
        #     Digital-7 Mono  数码管数字**够不到基线**  约 0.025 × 字号(40 号 1px)
        # 这两段之和(当前字号下 4px)就是还要再往下压的量。
        # 它随字号**线性**变,所以按字号算 —— 滚轮调完字号之后,底边仍然是齐的。
        st_size = self.cfg.get_int("Display", "status_font_size")
        t2_size = self.cfg.get_int("Display", "timer2_font_size")
        ascent_t2 = int(self.root.tk.call(
            "font", "metrics", (FONT_FAMILY, t2_size, FONT_WEIGHT), "-ascent"))
        ascent_st = int(self.root.tk.call(
            "font", "metrics", (FONT_FAMILY_STATUS, st_size, FONT_WEIGHT), "-ascent"))
        ink_drop = round(0.12 * st_size + 0.025 * t2_size)
        status_y = t2_y + ascent_t2 - ascent_st - STATUS_PADY - ink_drop
        self.status_label.place(x=status_x, y=status_y)
        self.root.update_idletasks()

        need_w = max(self.cfg.get_int("Display", "window_w"),
                     40 + self.time_label.winfo_reqwidth() + self.sec_label.winfo_reqwidth(),
                     status_x + self._status_reserved_width() + 20)
        need_h = max(self.cfg.get_int("Display", "window_h"),
                     t2_y + self.time_label2.winfo_reqheight() + 12,
                     status_y + self.status_label.winfo_reqheight() + 12)
        self.root.geometry(_fmt_geometry(need_w, need_h, self._pos[0], self._pos[1]))

        if self.edit_mode:
            self.edit_hint.place(relx=0.5, y=need_h - 26, anchor="n")
            self.edit_border.place(x=0, y=0, width=need_w, height=need_h)

        # ⚠️ 主显示区(主计时器 / 秒表)必须**最后**摆,而且只能在这里摆。
        #
        # sec_label 的 x 是 _apply_view_mode 按"主计时器当前的宽度"算出来的**定值**,
        # 算完就存住了 —— 主计时器之后变窄,它不会自己跟着动。而字号一变(滚轮)
        # 主计时器就变窄,所以**每次改字号都得重算**,否则秒表会钉在旧的右边缘上
        # 戳到主计时器外面去(实测:87 号滚到 67 号,超出 65px)。
        #
        # 放在 _relayout 末尾而不是各调用点,是因为 _relayout 正是"按当前字号
        # 重新摆放控件"的那个函数 —— 摆完主显示区才算摆完,新调用点也不会漏。
        self._apply_view_mode()

    def _apply_style(self):
        fam = FONT_FAMILY
        fam_status = FONT_FAMILY_STATUS
        self.bg_color = COLOR_BG

        self.root.configure(bg=self.bg_color)
        self.root.attributes("-alpha",
                             max(0.1, min(1.0, self.cfg.get_float("Display", "opacity"))))
        # 背景色即透明色 —— 整个背景点击穿透,不影响游戏操作
        if not self.edit_mode:
            self.root.attributes("-transparentcolor", self.bg_color)

        self.time_label.config(font=(fam, self.cfg.get_int("Display", "font_size"), FONT_WEIGHT),
                               bg=self.bg_color, fg=self._main_color())
        # 秒表字号**故意**取和主计时器同一个来源,没有独立的配置键 ——
        # 两者是同一个位置互斥显示的(R 键切换),字号分开就会一切换就跳大小。
        self.sec_label.config(font=(fam, self.cfg.get_int("Display", "font_size"), FONT_WEIGHT),
                              bg=self.bg_color, fg=self._sec_color())
        self.time_label2.config(font=(fam, self.cfg.get_int("Display", "timer2_font_size"), FONT_WEIGHT),
                                bg=self.bg_color, fg=self._sec2_color())
        # 状态文字用另一个字体族 —— 内容是中文,数字字体里没有这些字形。
        # 颜色跟第二计时器同源(用户点名要同步),别写死 —— 见 _apply_sec2_color
        self.status_label.config(font=(fam_status, self.cfg.get_int("Display", "status_font_size"), FONT_WEIGHT),
                                 bg=self.bg_color, fg=self._sec2_color())
        self.edit_border.config(bg=self.bg_color,
                                highlightbackground=COLOR_EDIT_BORDER)
        self.edit_hint.config(bg=self.bg_color, fg=COLOR_EDIT_BORDER)

    def _main_color(self):
        # 三色:初始色(还没按过 F1)/ 启用态(虚化)/ 停用态
        if not self._main_color_touched:
            return COLOR_MAIN
        return COLOR_MAIN_ON if self.active else COLOR_MAIN_OFF

    def _sec_color(self):
        return COLOR_SEC_ON if self.sec_active else COLOR_SEC_OFF

    def _sec2_color(self):
        """第二计时器专用:亮 = 没虚化(timer2_dimmed=False),灰 = 虚化。

        ⚠️ 别和秒表的 _sec_color 合并成一个函数 —— 两者外形像,但状态源不同:
        秒表只看 sec_active(F3),第二计时器**只看 timer2_dimmed**。
        ⚠️ 别把 sec_active 掺进来:2026-10-14 深夜用户实测抓到 —— 曾写成
        `sec_active and not timer2_dimmed`,后果是 F3 停用秒表后第二计时器
        **永远灰**(F2 给了窗口也亮不起),两个无关的东西被联动。测试有回归用例。

        ⚠️ timer2_dimmed 的维护点(2026-10-15 定稿后只剩三处):
        初始 **False**(常亮);点左键起表**立刻**置 True(计时中一直灰);
        F2 偷看置 False、3 秒后 _dim_timer2 置回 True。别再写「counting_up 就
        保持亮」这类规则(2026-10-15 起计时中就是灰的),也别在起表处排倒计时
        (用户点名「立刻虚化,不用等待三秒」)。
        """
        on = not self.timer2_dimmed
        return COLOR_SEC_ON if on else COLOR_SEC_OFF

    def _apply_sec2_color(self):
        """把第二计时器的当前颜色**同时**刷给状态文字。

        2026-10-14 用户点名:"文字保持蓝色看起来很丑,改成跟第二计时器的颜色
        同步吧" —— 虚化变灰时「等待左键 / 进攻 / 平静」跟着一起灰,亮起时一起回青。
        ⚠️ 两边只许从 _sec2_color() 这一个来源取色:别再给 status_label 单配颜色
        (原 COLOR_STATUS 常量已删),否则迟早又不同步。
        调用点 = 所有会改变第二计时器颜色的地方(F2 偷看/进等待 / 起表立刻虚化 /
        偷看到点回灰 / 改字号 / 改计时参数)。⚠️ F3(秒表)不在列 —— 秒表与第二计时器互不影响,
        别在 handle_f3_key 里再调它(2026-10-14 深夜修过的联动 bug)。
        """
        c = self._sec2_color()
        self.time_label2.config(fg=c)
        self.status_label.config(fg=c)

    # ==================================================================
    # 主循环:只在"显示真的会变"的时刻唤醒
    # ==================================================================
    @staticmethod
    def _until_next_second(value):
        """距 int(value) 下一次变化还有多少毫秒。

        ⚠️ 末尾的 +2ms 是故意的,别去掉:定时器只会**晚**醒不会早醒,而算
        delay 用的 now 是这一帧开头取的,到真正 after() 时已经旧了零点几毫秒。
        正好卡在边界上算,实际就会**早**零点几毫秒醒来 —— 那一帧看到的还是
        旧值,只能再补一次唤醒,白白多等一个来回。落点放到边界之后 2ms,
        一次到位。下限 3ms 只是防 0 延迟自旋。
        """
        return max(3, int((1.0 - (value % 1.0)) * 1000) + 2)

    def _tick(self):
        self._tick_id = None

        # 定时器精度:有计时器在跑才要 1ms,全停了就还回去。
        # ⚠️ 必须在算 delay / 排 after() **之前**调 —— 精度决定这一帧的等待
        # 能醒多准,排完再调就慢了一整帧。
        self._sync_timer_resolution()

        # 配置文件热重载
        try:
            if self.cfg.changed_on_disk():
                self._reload_from_disk()
        except Exception:
            pass

        # 捕获超时。走 _cancel_capture 而不是自己清 _capturing ——
        # 它顺便会把那一行的青色高亮撤掉(超时是三个出口里最容易被漏掉的那个)
        if self._capturing and time.monotonic() > self._capture_deadline:
            self._cancel_capture()

        now = time.monotonic()
        delay = 1000  # 空闲时也每秒醒一次,顺便轮询配置文件

        # ---- 主计时器归零判定 ----
        if self.state == "running" and (now - self.start_time) >= self.main_max:
            self.reset_timer()

        # ---- 主显示区 ----
        if self.show_sec_mode:
            self.sec_label.config(text="{:02d}".format(self._stopwatch_seconds(now)))
            if self.new_sec_running:
                delay = min(delay, self._until_next_second(now - self.new_start_sec))
        else:
            elapsed = self._main_elapsed(now)
            minutes, seconds = divmod(int(elapsed), 60)
            self.time_label.config(text="{:02d}:{:02d}".format(minutes, seconds))
            if self.state == "running":
                delay = min(delay, self._until_next_second(elapsed))

        # ---- 第二个计时器 ----
        if self.state2 == "counting_up":
            elapsed2 = now - self.start_time2
            minutes2, seconds2 = divmod(int(elapsed2), 60)
            self.time_label2.config(text="{:02d}:{:02d}".format(minutes2, seconds2))
            delay = min(delay, self._until_next_second(elapsed2))
            self._update_phase(minutes2)

        self._update_status_label()
        self._tick_id = self.root.after(delay, self._tick)

    def _wake_now(self):
        """立刻跑一帧,别等下一次空闲唤醒。

        ⚠️ 凡是**改了显示状态**的 handler 都要在最后调它。tick 是按需唤醒的:
        空闲周期 1000ms,而且唤醒时刻是对齐到"上一个正在跑的计时器"的秒边界的
        —— 启动 / 重启一个计时器时,那个待唤醒的 tick 还挂在**旧**的节奏上,
        不叫醒它会有两个后果:

          1. 显示停在旧值上最多 1 秒(秒表重启时表现为上一轮的数字赖着不走);
          2. 秒边界要等下一帧才重新对齐,第一秒被顶到 1 秒多。

        ⚠️ 只给 handler 调,**不要**放进 reset_timer 这类会被 _tick 自己调用的
        函数里 —— _tick 里再调 _tick 会各排一个 after,循环就分裂成两条了。
        """
        if self._tick_id:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None
        self._tick()

    def _sync_timer_resolution(self):
        """有任何计时器在跑 → 1ms 精度;全停 → 还回系统默认。

        空闲时不占着 1ms 精度:它会让本进程的定时器唤醒从每秒 64 次涨到
        最多 1000 次,白耗电 —— 而这程序常驻托盘,大部分时间是空闲的。
        """
        want = (self.state == "running" or self.state2 == "counting_up"
                or self.new_sec_running)
        if want == self._hi_res:
            return
        self._hi_res = want
        _set_timer_precision(want)

    def _main_elapsed(self, now):
        if self.state == "running":
            return now - self.start_time
        if self.state == "paused":
            return self.elapsed_time
        return 0.0

    def _stopwatch_seconds(self, now):
        if not self.new_sec_running:
            return 0
        elapsed = now - self.new_start_sec
        if elapsed >= self.stopwatch_max:
            self.new_sec_running = False
            return 0
        return int(elapsed)

    def _update_phase(self, minutes):
        if minutes == self.last_min2:
            return
        self.last_min2 = minutes
        if minutes < 1:
            self._phase_text = self.PHASE_CALM
        else:
            cycle = (minutes - 1) // self.phase_minutes
            self._phase_text = self.PHASE_ATTACK if cycle % 2 == 0 else self.PHASE_CALM

    def _update_status_label(self):
        if self._capturing:
            self.status_label.config(text="请按键…")
        elif self.state == "paused" and not self.force_hide_pause_text:
            self.status_label.config(text="已 暂 停")
        elif self.timer2_waiting:
            # 2026-10-15 起「等待左键」是常亮的:waiting 与 armed 同步,文字
            # 跟着整个等待状态走,点左键起表(或别的转换)才消失。armed 条件
            # 留着当双保险,与左键守卫同款(见 handle_left_click_timer2)。
            self.status_label.config(text="等待左键" if self.timer2_armed else "")
        elif self.state2 == "counting_up":
            self.status_label.config(text=self._phase_text)
        else:
            self.status_label.config(text="")

    def _apply_view_mode(self):
        """切主显示 / 秒表显示 —— 只在模式变化时摆一次控件,不再每帧重摆。"""
        if self.show_sec_mode:
            self.time_label.place_forget()
            # 秒表右边缘贴住主计时器的右边缘。place 的 anchor="ne" 把锚点放在
            # 控件右上角,所以秒数从 99 涨到 100 变宽时是往左长,右边缘不动。
            self.root.update_idletasks()
            main_right = 20 + self.time_label.winfo_reqwidth()
            self.sec_label.place(x=main_right, y=20, anchor="ne")
        else:
            self.sec_label.place_forget()
            self.time_label.place(x=20, y=20)

    # ==================================================================
    # 热键与鼠标
    # ==================================================================
    def _start_listeners(self):
        threading.Thread(target=lambda: keyboard.Listener(
            on_press=self._on_key_press, on_release=self._on_key_release).start(),
            daemon=True).start()
        threading.Thread(target=lambda: MouseListener(
            on_click=self._on_mouse_click).start(),
            daemon=True).start()

    def _on_key_press(self, key):
        try:
            name = base_key_name(key)

            mod = MODIFIER_KEYS.get(key)
            if mod:
                self._pressed_mods.add(mod)
                return

            if name is None:
                return

            # ---- 捕获新按键 ----
            if self._capturing:
                if key == Key.esc:
                    self.root.after(0, self._cancel_capture)
                    return
                # 改键窗口里按住不放会连发,挡一下免得重复提交
                if name in self._held_keys:
                    return
                self._held_keys.add(name)
                spec = "+".join(sorted(self._pressed_mods) + [name])
                self.root.after(0, lambda s=spec: self._finish_capture(s))
                return

            # ---- 正常派发 ----
            # 不做全局去重:按住热键不放,系统会持续补发 press 事件,热键就跟着
            # 连发 —— 这是原版行为(原版只有 R 键有 _r_lock,其它键按住连发)。
            # 只有「切换主显示 / 秒表」保留锁,按住只切一次,免得画面疯狂闪烁。
            action = match_hotkey(self.hotkeys, name, frozenset(self._pressed_mods))
            if action is None:
                return
            if action == "toggle_stopwatch_view":
                if name in self._held_keys:
                    return
                self._held_keys.add(name)
            self.root.after(0, lambda a=action: self._dispatch(a))
        except Exception:
            pass

    def _on_key_release(self, key):
        try:
            mod = MODIFIER_KEYS.get(key)
            if mod:
                self._pressed_mods.discard(mod)
                return
            name = base_key_name(key)
            if name:
                self._held_keys.discard(name)
        except Exception:
            pass

    def _on_mouse_click(self, x, y, button, pressed):
        if not pressed or self.edit_mode:
            # 编辑模式下交给 tkinter 自己处理拖动和右键退出
            return
        name = base_mouse_name(button)
        if name is None:
            return

        # ---- 捕获新按键 ----
        # 和 _on_key_press 里那段对称:按下的鼠标键直接存成新的热键。
        # Esc 取消走的是键盘那条路(_on_key_press),_on_key_release 一直在跑,照常有效。
        if self._capturing:
            spec = "+".join(sorted(self._pressed_mods) + [name])
            self.root.after(0, lambda s=spec: self._finish_capture(s))
            return

        # ---- 正常派发 ----
        # ⚠️ 这里**不能**再写 `and not self.active` / `and self.timer2_waiting` 这类
        # 状态条件 —— 条件已经挪进各自的 handler 里了(handle_right_click 开头就有
        # `if self.active: return`)。留在这儿的话,鼠标键一旦被改绑到别的动作,
        # 那个动作会连条件一起继承过去,变成"只有停用时才响应"的怪行为。
        action = match_hotkey(self.hotkeys, name, frozenset(self._pressed_mods))
        if action is None:
            return
        self.root.after(0, lambda a=action: self._dispatch(a))

    def _dispatch(self, action):
        handler = {
            "toggle_active": self.handle_f1_key,
            "reset_second": self.handle_f2_key,
            "toggle_stopwatch_active": self.handle_f3_key,
            "pause_resume": self.handle_space_key,
            "stopwatch_start": self.handle_stopwatch_start,
            "toggle_stopwatch_view": self.handle_stopwatch_view,
            "close": self.close_program,
            "click_second": self.handle_left_click_timer2,
            "click_reset": self.handle_right_click,
        }.get(action)
        if handler:
            handler()

    # ==================================================================
    # 原有功能(语义与原版一致)
    # ==================================================================
    def handle_f1_key(self):
        self.active = not self.active
        self._main_color_touched = True
        self.time_label.config(fg=self._main_color())

    def handle_f3_key(self):
        self.sec_active = not self.sec_active
        # 只刷秒表自己的颜色。⚠️ 第二计时器(F2)与秒表互不干涉 ——
        # 2026-10-14 深夜修:这里曾顺手调 _apply_sec2_color(),叠上 _sec2_color
        # 里混进的 sec_active,按 F3 会把第二计时器/状态文字当场压灰,
        # 停用秒表后 F2 再也亮不起(用户实测抓到,测试有回归用例)。
        self.sec_label.config(fg=self._sec_color())

    def handle_space_key(self):
        if self.active:
            return
        if self.state == "running":
            self.pause_timer()
        elif self.state == "paused":
            self.start_timer()

    def handle_right_click(self):
        if self.active:
            return
        if self.pause_hide_after_id:
            self.root.after_cancel(self.pause_hide_after_id)
            self.pause_hide_after_id = None
        self.force_hide_pause_text = False
        self.reset_timer()
        self.start_timer()

    def handle_stopwatch_start(self):
        if not self.sec_active:
            return
        self.new_sec_running = True
        self.new_start_sec = time.monotonic()
        # ⚠️ 必须立刻跑一帧。少了它,两种情况都会慢:
        #   - 重启(已经走到 45 再按 T):标签继续显示 45,最多赖 1 秒才跳回 00,
        #     而"00 -> 01"还得从**旧**的秒边界再等一次,第一秒被顶到 1 秒多;
        #   - 首次启动:显示本来就是 00,看不出脏值,但秒边界同样没对齐,
        #     0 -> 1 的跳变会晚最多 1 秒。
        self._wake_now()

    def handle_stopwatch_view(self):
        self.show_sec_mode = not self.show_sec_mode
        self._apply_view_mode()
        # 切完立刻跑一帧。不然新露出来的那块显示的是"上次离开这个模式时的旧数字"
        # —— 被藏起来的显示在整个隐藏期间都不刷新,所以按 R 时会看到数字跳一大截,
        # 跳的幅度等于在另一个模式待了多久。顺便把下一帧重新对齐到新计时器的
        # 秒边界,否则还会按另一个计时器的节奏更新。
        self._wake_now()

    def start_timer(self):
        self.state = "running"
        self.force_hide_pause_text = False
        # 用单调时钟:不受系统时间被 NTP 校正 / 手动修改的影响
        self.start_time = time.monotonic() - self.elapsed_time
        self.pause_hide_after_id = None
        self._update_status_label()
        # 续跑:不立刻跑一帧的话,秒边界还是暂停前的旧节奏,下一次跳秒
        # 能晚到 1 秒(比如 12.4 秒暂停、续跑,00:13 该在 +0.6s 出现,
        # 却要等到那帧 tick 醒来才对齐)
        self._wake_now()

    def pause_timer(self):
        self.state = "paused"
        self.force_hide_pause_text = False
        self.elapsed_time = time.monotonic() - self.start_time
        if self.pause_hide_after_id:
            self.root.after_cancel(self.pause_hide_after_id)
        self.pause_hide_after_id = self.root.after(self.pause_hide_ms, self.clear_pause_text)
        # 冻结值 / 「已 暂 停」立刻上屏,不等下一次空闲唤醒
        self._wake_now()

    def clear_pause_text(self):
        self.force_hide_pause_text = True
        self.pause_hide_after_id = None
        self._update_status_label()

    def reset_timer(self):
        self.state = "stopped"
        self.force_hide_pause_text = False
        self.elapsed_time = 0.0
        self.time_label.config(text="00:00")
        self._update_status_label()

    def handle_f2_key(self):
        # 两种走法(2026-10-15 用户定稿,见测试第一段;旧「其余一切=归零+3 秒窗」
        # 已退役):
        #   虚化中(⟺正在计时)按 F2 = 「偷看」:亮起来看数字,排 3 秒倒计时,
        #     计时照走不清零;3 秒内没再按 F2 就自动回灰。
        #   其余一切(空闲 / 等待左键中 / 偷看窗口内再按)= 进「等待左键」:
        #     归零 + **常亮,不排倒计时** —— 等多久都亮着,点左键才起表。
        # ⚠️ 用户原话:「所有的等待状态都是常亮的」「如果按了 f2 则进入等待状态,
        # 并且不会自动进入虚化状态」—— 别给等待状态加任何自动虚化。
        # ⚠️ 别再写成"按 F2 一律归零":计时中虚化后想看一眼就把表清零了,
        # 用户实测点名"不会影响第二计时器的计时"。
        # (初始状态 dimmed 是 False —— 一开始就常亮;靠 state2 卡"没在计时"的
        # 情况一律进等待,别只判 dimmed。)
        if self.timer2_dimmed and self.state2 == "counting_up":
            self.timer2_dimmed = False
            # 偷看时 armed 保持 False(表在走,左键本来也不该重开;
            # 守卫里还有 timer2_waiting 一道,这里双保险)。
            self.timer2_armed = False
            self._apply_sec2_color()
            self._schedule_dim_timer2()
            self._update_status_label()
            return
        self.state2 = "stopped"
        self.time_label2.config(text="00:00")
        self._arm_timer2()
        self.last_min2 = -1
        self._update_status_label()

    def _arm_timer2(self):
        """进「等待左键」:亮起 + 开放左键(归零/文字刷新由调用方做)。

        2026-10-15 起**不排虚化倒计时** —— 等待状态常亮,等多久都行
        (用户定稿「所有的等待状态都是常亮的」)。顺手取消可能残留的偷看
        倒计时(正常到不了这:偷看时不在等待;留着是双保险,防止过期回调
        把常亮的等待又压灰 —— 测试第一段的等待回归那条就是盯这个)。
        """
        self._cancel_dim_timer2()
        self.timer2_waiting = True
        self.timer2_armed = True
        self.timer2_dimmed = False
        self._apply_sec2_color()

    def _schedule_dim_timer2(self):
        """(重)起偷看的 3 秒虚化倒计时 —— **唯一调用点是 handle_f2_key 的偷看分支**。

        2026-10-15 用户定稿:计时中按 F2 脱离虚化看一眼,「如果脱离后没有再按
        f2,过三秒自动进入虚化状态」。⚠️ 起表**不再**走它(点左键起表=立刻虚化,
        用户点名「不用等待三秒」);进「等待左键」也**不走**它(常亮,不排倒计时)。
        别照旧文档当"起表重置回满 3 秒"再加回去。
        """
        self._cancel_dim_timer2()
        self._timer2_dim_id = self.root.after(
            int(DIM_TIMEOUT_S * 1000), self._dim_timer2)

    def _cancel_dim_timer2(self):
        if self._timer2_dim_id:
            try:
                self.root.after_cancel(self._timer2_dim_id)
            except Exception:
                pass
            self._timer2_dim_id = None

    def _dim_timer2(self):
        """偷看窗口到点:收回虚化(变灰),计时照走 —— 数字变灰继续。

        2026-10-15 起这个倒计时只在**偷看**时排(见 _schedule_dim_timer2),
        别处不排;进「等待左键」时由 _arm_timer2 主动取消,防止过期回调
        把常亮的等待压灰。「等待左键」不再有虚化形态,这里回来时必然在计时中。
        """
        self._timer2_dim_id = None
        self.timer2_armed = False
        self.timer2_dimmed = True
        self._apply_sec2_color()
        # 回来时状态文字正显示「进攻 / 平静」,刷一次让颜色与状态同帧同步,
        # 不等 _tick 下一帧(原为「等待左键」消失准备的,留着兜底)。
        self._update_status_label()

    def handle_left_click_timer2(self):
        # ⚠️ 这个守卫原先写在鼠标监听里(`elif button == Button.left and
        # self.timer2_waiting:`)。鼠标键改成走 match_hotkey 之后那儿不能再判状态,
        # 守卫必须搬进 handler —— 少了它,左键在**任何状态下**都会启动第二计时器。
        #
        # 2026-10-15 起:等待左键是常亮的,armed 与 waiting 同步置位,
        # 左键只在「等待左键」时有效;空闲/计时中一律无效(守卫两道都要)。
        if not self.timer2_waiting or not self.timer2_armed:
            return
        # 起表 = **立刻虚化**(2026-10-15 用户定稿:「如果按左键开始计时了立刻
        # 进入虚化状态,不用等待三秒」—— 起表后亮 3 秒的旧规则退役)。
        # ⚠️ 不许改回排倒计时 / 不置灰:计时中就该是灰的,想看一眼按 F2。
        self.timer2_armed = False      # armed 只属于「等待左键」,起表即作废
        self.timer2_waiting = False
        self.state2 = "counting_up"
        self.start_time2 = time.monotonic()
        self.timer2_dimmed = True
        self._apply_sec2_color()
        self.last_min2 = -1
        # ⚠️ 必须先算一次相位,再刷状态文字。
        #
        # _phase_text 只在 _tick -> _update_phase() 里赋值,而 tick 的空闲周期是
        # 1000ms。少了这一句,点完左键 status_label 会拿到还没赋过值的 _phase_text
        # (启动时是空字符串)—— 「等待左键」先消失、状态栏**空一下**,最快也要等
        # 到下一帧才跳出「平静」,看着就像平静来晚了。
        #
        # 这里 elapsed2 = 0,所以相位就是 0 分钟那个;顺便把 last_min2 也置成 0,
        # 下一帧 _update_phase(0) 会因为 minutes == last_min2 直接返回,不会重复算。
        self._update_phase(0)
        self._update_status_label()

    def close_program(self):
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        try:
            if self._tick_id:
                self.root.after_cancel(self._tick_id)
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        # 托盘线程不一定能干净退出,直接结束进程保证不留后台
        os._exit(0)

    # ==================================================================
    # 编辑模式
    # ==================================================================
    def _enter_edit_mode(self):
        if self.edit_mode:
            return
        self.edit_mode = True

        # 关掉透明色,让整个窗口变成实心可点区域
        self.root.attributes("-transparentcolor", TRANSPARENT_DISABLED)
        self.edit_border.place(x=0, y=0,
                               width=self.root.winfo_width(),
                               height=self.root.winfo_height())
        self.edit_border.lower()
        self.edit_hint.config(text="拖动移动 · 滚轮调字号 · 右键退出")
        self.edit_hint.place(relx=0.5, y=self.root.winfo_height() - 26, anchor="n")
        self._bind_drag(True)
        self._refresh_tray()

    def _exit_edit_mode(self, save=True):
        if not self.edit_mode:
            return
        self.edit_mode = False
        self._bind_drag(False)
        self.edit_border.place_forget()
        self.edit_hint.place_forget()
        self.root.attributes("-transparentcolor", self.bg_color)

        if save:
            self.cfg.set("Display", "window_x", self._pos[0])
            self.cfg.set("Display", "window_y", self._pos[1])
            self.cfg.save()
        self._refresh_tray()

    def _bind_drag(self, on):
        widgets = (self.root, self.edit_border, self.edit_hint,
                   self.time_label, self.sec_label, self.status_label, self.time_label2)
        pairs = (
            ("<ButtonPress-1>", self._on_drag_start),
            ("<B1-Motion>", self._on_drag_move),
            ("<ButtonRelease-1>", self._on_drag_end),
            ("<MouseWheel>", self._on_wheel),
            ("<Button-3>", self._on_edit_right_click),
        )
        for w in widgets:
            for seq, fn in pairs:
                if on:
                    w.bind(seq, fn, add="+")
                else:
                    w.unbind(seq)

    def _on_drag_start(self, event):
        self._drag_offset = (event.x_root - self._pos[0],
                             event.y_root - self._pos[1])

    def _on_drag_move(self, event):
        if not self._drag_offset:
            return
        self._pos = (event.x_root - self._drag_offset[0],
                     event.y_root - self._drag_offset[1])
        self.root.geometry(_fmt_geometry(self.root.winfo_width(),
                                         self.root.winfo_height(),
                                         self._pos[0], self._pos[1]))

    def _on_drag_end(self, event):
        self._drag_offset = None
        self.cfg.set("Display", "window_x", self._pos[0])
        self.cfg.set("Display", "window_y", self._pos[1])
        self.cfg.save()

    def _on_wheel(self, event):
        # Windows 上 event.delta 是 ±120 的倍数
        self._bump_font(1 if event.delta > 0 else -1)

    def _on_edit_right_click(self, event):
        self._exit_edit_mode()

    def _apply_font_delta(self, delta):
        # 没有 sec_font_size —— 秒表跟着 font_size 走,见 _apply_style
        for key in ("font_size", "timer2_font_size", "status_font_size"):
            val = max(8, min(200, self.cfg.get_int("Display", key) + delta))
            self.cfg.set("Display", key, val)
        self.cfg.save()
        self._apply_style()
        self._relayout()
        # ⚠️ 2026-10-15 补:这条路径原来不刷「设置」窗口的行值 —— 点 +/− 后
        # 窗口里的数字不跟着动(得等别的东西触发刷新)。行改成可输入后必须刷,
        # 不然显示和实际值脱节。
        self._refresh_tweak_values()

    def _bump_font(self, direction):
        self._apply_font_delta(direction * self.cfg.get_int("Display", "font_step"))

    def _set_font(self, size):
        """输入框提交:输入的是**主字号**,差值应用到三个键(与 _bump_font 同一套)。

        ⚠️ 别把差值再乘 font_step —— 那是 _bump_font 的"方向"语义,写混会过冲
        (老 _reset_fonts 的说明里踩过同样的坑)。
        """
        self._apply_font_delta(max(8, min(200, size)) - self.cfg.get_int("Display", "font_size"))

    # ==================================================================
    # 托盘
    # ==================================================================
    def _tray_call(self, fn):
        """pystray 的回调在托盘线程里跑,统一切回 Tk 主线程执行。"""
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _start_tray(self):
        try:
            image = Image.open(_resource_path(ICON_FILENAME))
        except Exception:
            image = Image.new("RGBA", (64, 64), (26, 26, 26, 255))

        menu = pystray.Menu(
            pystray.MenuItem("编辑模式", lambda: self._tray_call(self._toggle_edit_mode),
                             checked=lambda item: self.edit_mode),
            pystray.Menu.SEPARATOR,
            # 2026-10-14 起「透明度…」和「修改热键…」合并成一个窗口 ——
            # 里面分区:外观(透明度/字号)、计时(上限)、热键。
            pystray.MenuItem("设置…", lambda: self._tray_call(self._open_hotkey_window)),
            pystray.Menu.SEPARATOR,
            # 2026-10-14 晚用户点名:重新载入配置要挪到打开配置文件**正下面**
            # (原来在"使用说明"后面)—— 两个都是"跟配置文件打交道"的,挨着好找。
            pystray.MenuItem("打开配置文件", lambda: self._tray_call(self._open_config)),
            pystray.MenuItem("重新载入配置", lambda: self._tray_call(self._reload_from_disk)),
            pystray.MenuItem("使用说明", lambda: self._tray_call(self._open_manual)),
            # 「重置窗口位置」的撤销并进了下面「恢复上次设置」(重置走
            # save(force_snapshot=True),快照必定是"点重置前一瞬间") ——
            # 2026-10-14 晚用户点名:"包含的话就把恢复上次位置删了",已删。
            pystray.MenuItem("重置窗口位置", lambda: self._tray_call(self._reset_position)),
            # 整份设置的还原点 = config.ini 旁边的自动快照(五槽轮转:config.prev.ini
            # ~ config.prev5.ini,见 Config.save);点一次往回退一层,再点继续退。
            # 快照由"保存"创建,而菜单重建才刷新置灰:enabled 和上面的 checked 一样,
            # 是**重建菜单时**求值,win32 菜单建一次就复用、不会自己刷 —— Config.save
            # 建快照时会通过 snapshot_hook 调一次 _refresh_tray,别把那根线剪了。
            pystray.MenuItem("恢复上次设置", lambda: self._tray_call(self._restore_settings),
                             enabled=lambda item: os.path.exists(self._prev_settings_path())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self._tray_call(self.close_program)),
        )

        self._tray = pystray.Icon("PhasmoTimer", image, APP_TITLE, menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _toggle_edit_mode(self):
        if self.edit_mode:
            self._exit_edit_mode()
        else:
            self._enter_edit_mode()

    def _refresh_tray(self):
        try:
            if self._tray:
                self._tray.update_menu()
        except Exception:
            pass

    def _set_opacity(self, frac):
        val = max(0.1, min(1.0, round(frac, 2)))
        self.cfg.set("Display", "opacity", val)
        self.cfg.save()
        self._apply_style()
        self._refresh_tweak_values()

    def _bump_opacity(self, delta):
        self._set_opacity(self.cfg.get_float("Display", "opacity") + delta)

    # ------------------------------------------------------------------
    # 独立透明度小窗已删(2026-10-14):并进「修改」窗口的「外观」区,
    # 托盘菜单也只剩一个「修改…」。别照着旧记忆重建这个窗口。
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 「修改」窗口 —— 外观(透明度/字号)+ 计时(上限)+ 热键,2026-10-14 合并
    # ------------------------------------------------------------------
    def _open_hotkey_window(self):
        if self._hotkey_win and self._hotkey_win.winfo_exists():
            self._hotkey_win.lift()
            self._hotkey_win.focus_force()
            return

        # 漏在 HOTKEY_GROUPS 外面的动作兜到「其它」,免得它从窗口里凭空消失
        covered = set()
        for _caption, acts in HOTKEY_GROUPS:
            covered.update(acts)
        leftover = tuple(a for a, _ in HOTKEY_DESCRIPTIONS if a not in covered)
        groups = list(HOTKEY_GROUPS) + ([("其它", leftover)] if leftover else [])

        # 无边框窗口:系统标题栏、关闭按钮、窗口阴影全都没有,全得自己画。
        # win 自己的底色当 1px 外框,body 再缩进 1px —— 不留这一圈描边的话,
        # 24 号灰贴在同为深色的桌面上会糊成一片,看不出窗口边界在哪。
        win = tk.Toplevel(self.root)
        self._hotkey_win = win
        win.title("设置")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=HK_BORDER)

        body = tk.Frame(win, bg=HK_BG)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        # ---- 自绘标题栏(整条都能拖) ----
        titlebar = tk.Frame(body, bg=HK_BG)
        titlebar.pack(fill="x")
        title = tk.Label(titlebar, text="设置", bg=HK_BG, fg=HK_TEXT,
                         font=(FONT_FAMILY_STATUS, 10, "bold"))
        title.pack(side="left", padx=(14, 0), pady=(10, 9))
        close = tk.Label(titlebar, text="×", bg=HK_BG, fg=HK_DIM, cursor="hand2",
                         font=(FONT_FAMILY_STATUS, 13))
        close.pack(side="right", padx=(0, 10), pady=(4, 4))
        close.bind("<Button-1>", lambda e: self._close_hotkey_window())
        close.bind("<Enter>", lambda e: close.config(fg=HK_CLOSE_HOVER))
        close.bind("<Leave>", lambda e: close.config(fg=HK_DIM))

        def drag_start(ev):
            win._drag = (ev.x_root - win.winfo_x(), ev.y_root - win.winfo_y())

        def drag_move(ev):
            dx, dy = getattr(win, "_drag", (0, 0))
            win.geometry("+{}+{}".format(ev.x_root - dx, ev.y_root - dy))

        for w in (titlebar, title):
            w.bind("<Button-1>", drag_start)
            w.bind("<B1-Motion>", drag_move)

        tk.Frame(body, bg=HK_BORDER, height=1).pack(fill="x")
        hint = tk.Label(body, text="点一行选中,再按下希望改成的新键", bg=HK_BG, fg=HK_DIM,
                        font=(FONT_FAMILY_STATUS, 9))
        hint.pack(anchor="w", padx=15, pady=(10, 0))

        # 「外观」和「计时」的参数行统一由 _build_tweak_row 生成,数值实时刷
        # (_refresh_tweak_values)。各行只碰自己那几个 config 键,和热键/编辑模式互不干扰。
        # 只有 «外观» 用 HK_ACCENT —— 数值本来就是青色,呼应主窗口。
        self._tw = {}
        self._tw_file = None

        def sec_header(txt):
            tk.Label(body, text=txt, bg=HK_BG, fg=HK_DIM,
                     font=(FONT_FAMILY_STATUS, 9)).pack(anchor="w", padx=15, pady=(12, 3))

        sec_header("外观")
        self._build_tweak_row(body, {
            # 2026-10-15 用户点名:四行参数统一改成**可输入** —— 输入时只打数字,
            # 提交后程序自动补单位(「200」→「200秒」),数字和单位是同一段文本、
            # 同一个颜色;用户自己打的单位会被剥掉、强制换成程序单位
            # (机制见 _build_tweak_row 的 commit)。
            # ⚠️ 「点值恢复默认」由此**整体退休**(点击 = 落光标编辑,冲突);
            # 要回默认值直接在框里输,大回退还留着「恢复上次设置」兜底。
            "key": "opacity", "field": "窗口透明度", "unit": "%",
"lo": 10, "hi": 100,
            "val": lambda: int(round(self.cfg.get_float("Display", "opacity") * 100)),
            "step": lambda d: self._bump_opacity(0.05 * d),
            "set": lambda v: self._set_opacity(v / 100.0),
        })
        self._build_tweak_row(body, {
            # ⚠️ config 里仍是三个字号键(font_size / timer2_font_size /
            # status_font_size),比例锁死、永远一起动(见 _bump_font);
            # 界面上**合成一行**就够了 —— 2026-10-14 用户点名:三个字号其实
            # 是一个东西,就放一个「计时器字号」,不用多放。别再拆回三行。
            # 输入框里键入的是**主字号**,差值应用到三个键(见 _set_font)。
            "key": "font_size", "field": "计时器字号", "unit": "",
"lo": 8, "hi": 200,
            "val": lambda: self.cfg.get_int("Display", "font_size"),
            "step": lambda d: self._bump_font(d),
            "set": lambda v: self._set_font(v),
        })

        sec_header("计时")
        self._build_tweak_row(body, {
            # 上/下限:1~9 分钟。主计时器归零会自动重开(见 _tick),
            # 调这个就是调滚屏归零的周期。输入框里键入的数字按**分钟**算
            # (行上写的什么单位,输进去的就是什么单位)。
            "key": "main_max", "field": "主计时器上限", "unit": "分钟",
"lo": 1, "hi": 9,
            "val": lambda: self.cfg.get_int("Timer", "main_max") // 60,
            "step": lambda d: self._tweak_set("Timer", "main_max",
                                              max(60, min(540, self.cfg.get_int("Timer", "main_max") + d * 60))),
            "set": lambda v: self._tweak_set("Timer", "main_max", v * 60),
        })
        self._build_tweak_row(body, {
            # 2026-10-15 用户点名:①单位用**秒**(旧:分钟);②可输入。
            # 范围 10 秒~1 小时,输入超范围自动卡到边界;−/+ 步长 ±30 秒。
            "key": "stopwatch_max", "field": "秒表上限", "unit": "秒",
"lo": 10, "hi": 3600,
            "val": lambda: self.cfg.get_int("Timer", "stopwatch_max"),
            "step": lambda d: self._tweak_set("Timer", "stopwatch_max",
                                              max(10, min(3600, self.cfg.get_int("Timer", "stopwatch_max") + d * 30))),
            "set": lambda v: self._tweak_set("Timer", "stopwatch_max", v),
        })

        sec_header("热键")
        self._hotkey_rows = {}
        rows = tk.Frame(body, bg=HK_BG)
        rows.pack(fill="both", expand=True)
        for caption, actions in groups:
            tk.Label(rows, text=caption, bg=HK_BG, fg=HK_DIM,
                     font=(FONT_FAMILY_STATUS, 9)).pack(anchor="w", padx=15, pady=(9, 3))
            for action in actions:
                self._build_hotkey_row(rows, action)

        tk.Frame(body, bg=HK_BORDER, height=1).pack(fill="x", pady=(9, 0))
        self._hotkey_hint = tk.StringVar(value="")
        tk.Label(body, textvariable=self._hotkey_hint, bg=HK_BG, fg=HK_WARN,
                 font=(FONT_FAMILY_STATUS, 10, "bold")).pack(pady=(8, 10))

        self._refresh_hotkey_list()
        self._refresh_tweak_values()

        # 无边框窗口系统不给摆位置:按内容算出尺寸,再水平居中、纵向偏上 1/3
        # (比正中好看,也不会挡住任务栏)
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry("{}x{}+{}+{}".format(
            w, h, (win.winfo_screenwidth() - w) // 2, (win.winfo_screenheight() - h) // 3))
        win.lift()
        win.focus_force()
        # 无边框也拦一下 Alt+F4:不拦的话窗口被系统直接销毁,self._capturing
        # 和高亮状态会留在半路(要等 8 秒超时自己清)
        win.protocol("WM_DELETE_WINDOW", self._close_hotkey_window)

    def _tweak_flash(self, msg):
        """操作反馈:把提示写进窗口底部那行小字,1.8 秒后自己消失。

        和改键捕获共用一个 Label(_hotkey_hint);操作提示优先级低,
        不给它加自己的定时器 —— 到点用 after 再清一次,内容被别的流程
        覆盖了也无妨(只影响这行提示)。
        """
        if self._hotkey_hint is None:
            return

        def clear():
            hint = self._hotkey_hint
            if hint is None:
                return
            try:
                hint.set("")
            except tk.TclError:     # 窗口已被销毁
                pass

        try:
            self._hotkey_hint.set(msg)
            self.root.after(1800, clear)
        except tk.TclError:
            pass

    def _tweak_set(self, sec, key, value):
        """参数行的写入口:改 config、存盘、四处刷新(主窗口样式 / 设置窗口数值 /
        第二计时器颜色 / 状态栏)。只碰单键 —— 字号那行不走这里(要走 _set_font /
        _bump_font 才能让三个字号一起动),别拿这个函数单键改字号。"""
        self.cfg.set(sec, key, value)
        self.cfg.save()
        self._apply_style()
        self._refresh_tweak_values()
        # 第二计时器颜色与状态文字依赖字号/计时参数,统一刷一次(窗口没开时是空操作)
        self._apply_sec2_color()
        self._update_status_label()

    def _refresh_tweak_values(self):
        """把三个分区里所有参数行的数值重新读一遍(改完全局设置后调用)。

        每行的内容 = 值 + 单位(见 _fmt_tweak)。⚠️ 正在打字的输入框**跳过** ——
        否则旁边改个别的设置就把没提交的输入冲掉了;提交路径(commit /
        _commit_editing_entry)自己会把规范化后的值写回去。
        """
        for r in self._tw.values():
            w = r["val"]
            if not w.winfo_exists():
                continue
            if w.focus_get() is w:
                continue
            w.delete(0, "end")
            w.insert(0, self._fmt_tweak(r["spec"]))
        self._tw_file = None

    @staticmethod
    def _fmt_tweak(spec):
        """输入框的显示文本:「值 + 单位」一整段,同字体同颜色(如「300秒」)。"""
        return "{}{}".format(spec["val"](), spec.get("unit", ""))

    def _commit_editing_entry(self):
        """把当前正被编辑的参数行提交掉(没有在编辑的就什么都不做)。

        按 −/+ 之前、关设置窗口之前都会先扫一遍 —— 否则半截输入(比如已经
        打好的「200」还没回车)会被步进或关窗吞掉。
        """
        for r in self._tw.values():
            w = r["val"]
            if not w.winfo_exists():
                continue
            if w.focus_get() is w:
                r["commit"]()
                return

    def _build_tweak_row(self, parent, spec):
        """一行参数:左名称 + 右「− 输入框 +」。

        四行都是输入框(2026-10-15 用户点名):内容 = 值 + 单位一整段(如
        「300秒」),同字体同颜色。点击 = 落光标编辑(**首次点击全选**,直接
        打字就盖掉旧值;已聚焦时再点才放光标微调)。
        回车 / 失焦提交,提交规则:
          - 只认文本里的**第一段连续数字**(正则提出)—— 用户自己打的单位
            (「200分钟」「200s」)会被剥掉,**单位强制按行上的来**;
          - 空的 / 没有数字 → 还原成当前值;超范围卡到 [lo, hi];
          - 规范化后的「值+单位」直接写回输入框(提交时输入框通常还带着
            焦点,_refresh_tweak_values 会跳过它,不能指望那边刷)。
        ⚠️ 已退休:「点值恢复默认」—— 点击被落光标占了,两者冲突;要回默认值
        直接在框里输,大回退还有托盘「恢复上次设置」。
        commit 函数存进 self._tw[key]["commit"]。
        行高固定 30;输入框统一 width=7,四行等宽对齐。
        """
        row = tk.Frame(parent, bg=HK_BG, height=30)
        row.pack(fill="x")
        row.pack_propagate(False)

        name = tk.Label(row, text=spec["field"], bg=HK_BG, fg=HK_TEXT,
                        font=(FONT_FAMILY_STATUS, 10), anchor="w")
        name.pack(side="left", padx=(15, 8))

        box = tk.Frame(row, bg=HK_BG)
        box.pack(side="right", padx=(8, 14))

        def pad_button(text, cmd):
            def run():
                # 先让输入框失焦落定半截输入(失焦会走 commit),再步进 ——
                # 步进后的刷新才不会把"还聚焦着的输入框"整行跳过,数字和
                # config 脱节。焦点直接还给窗口本身。
                self._commit_editing_entry()
                try:
                    self._hotkey_win.focus_set()
                except tk.TclError:        # 窗口已销毁
                    pass
                cmd()
            # highlightthickness 设 0:否则按钮默认的焦点框会吃掉 2px,整列不齐
            b = tk.Button(box, text=text, command=run, takefocus=False,
                          bg=HK_CHIP_BG, fg=HK_TEXT, activebackground=HK_ROW_HOVER,
                          activeforeground=HK_TEXT, bd=0, relief="flat", width=2,
                          padx=0, pady=0, highlightthickness=0,
                          font=("Consolas", 11, "bold"))
            b.pack(side="left", padx=(0, 8))
            return b

        minus = pad_button("−", lambda: spec["step"](-1))
        container = tk.Frame(box, bg=HK_BG, width=64, height=24)
        container.pack(side="left")
        container.pack_propagate(False)

        val = tk.Entry(container, width=7, justify="center", bd=0,
                       relief="flat", bg=HK_CHIP_BG, fg=HK_ACCENT,
                       insertbackground=HK_ACCENT, highlightthickness=1,
                       highlightbackground=HK_BORDER, highlightcolor=HK_ACCENT,
                       font=("Consolas", 10, "bold"))
        val.pack(side="left", fill="both", expand=True, padx=4, pady=1)

        def commit_entry(s=spec, w=val):
            if not w.winfo_exists():
                return
            m = re.search(r"\d+", str(w.get()))
            if m is None:                          # 空的 / 没数字:还原
                v = s["val"]()
            else:
                v = max(s["lo"], min(s["hi"], int(m.group())))   # 超范围卡边界
            s["set"](v)
            w.delete(0, "end")
            w.insert(0, self._fmt_tweak(s))
        val.bind("<Return>", lambda e, f=commit_entry: f())
        val.bind("<FocusOut>", lambda e, f=commit_entry: f())

        def on_click(e, w=val):
            # 首次点击 = 聚焦 + 全选(连单位一起选),接着打字就是全新数值;
            # 已聚焦时放行给默认行为(落光标微调)。
            # "break" 压掉 Entry 类绑定的默认"落光标 + 清选区",保住全选。
            if w.focus_get() is not w:
                w.focus_set()
                w.selection_range(0, "end")
                return "break"
        val.bind("<Button-1>", on_click)

        plus = pad_button("+", lambda: spec["step"](+1))

        self._tw[spec["key"]] = {"row": row, "val": val, "spec": spec,
                                 "minus": minus, "plus": plus,
                                 "commit": commit_entry}

    def _build_hotkey_row(self, parent, action):
        """一行 = 左侧竖条 + 功能名 + 右侧键帽。整行一个 Frame,悬停高亮整块。"""
        row = tk.Frame(parent, bg=HK_BG, cursor="hand2")
        row.pack(fill="x")

        # 3px 竖条:平常和底色同色(等于隐形),捕获时亮成青色。
        # **一直占位**是故意的 —— 否则捕获时整行会往右挪 3px 抖一下。
        marker = tk.Frame(row, bg=HK_BG, width=3)
        marker.pack(side="left", fill="y")
        marker.pack_propagate(False)

        # ⚠️ 行高**由功能名这一列决定,键帽不参与** —— 键帽的 pady 必须是 0。
        # 原因:键帽内容有两种字体(ASCII 用 Consolas、鼠标键用雅黑),两种字体的
        # 行高不一样,一旦让键帽参与撑高,「鼠标」那两行会比别的行矮一截。
        # 让雅黑 10 的功能名撑高,键帽(高度更小)由 pack 自动垂直居中。
        name = tk.Label(row, text=HOTKEY_LABELS.get(action, action), bg=HK_BG,
                        fg=HK_TEXT, font=(FONT_FAMILY_STATUS, 10), anchor="w")
        name.pack(side="left", padx=(12, 8), pady=6)

        # 键帽:外面一个 1px 描边 Frame,里面才是文字(缩进 1px 就是描边)
        chip = tk.Frame(row, bg=HK_BORDER)
        chip.pack(side="right", padx=(8, 14))
        chip_text = tk.Label(chip, text="", bg=HK_CHIP_BG, fg=HK_CHIP_TEXT,
                             font=_chip_font(""), padx=9, pady=2)
        chip_text.pack(padx=1, pady=1)

        self._hotkey_rows[action] = {"row": row, "marker": marker, "name": name,
                                     "chip": chip, "chip_text": chip_text}

        for w in (row, marker, name, chip, chip_text):
            w.bind("<Enter>", lambda e, a=action: self._hover_row(a, True))
            w.bind("<Leave>", lambda e, a=action: self._row_leave(a))
            w.bind("<Button-1>", lambda e, a=action: self._pick_row(a))

    def _hover_row(self, action, on):
        r = self._hotkey_rows.get(action)
        if not r or self._capturing == action:
            return   # 捕获中那行的颜色归 _paint_capture_state 管,悬停不许覆盖
        color = HK_ROW_HOVER if on else HK_BG
        r["row"].config(bg=color)
        r["marker"].config(bg=color)
        r["name"].config(bg=color)

    def _row_leave(self, action):
        """指针真的离开这一行,才撤高亮。

        ⚠️ 不能收到 Leave 就直接撤:行内还有子控件,指针从「行」挪到「功能名」
        上时,Tk 会先给行发 Leave、再给子控件发 Enter —— 直接撤就会闪一下。
        这里用指针坐标确认它还在不在这一行的矩形里。
        """
        r = self._hotkey_rows.get(action)
        if not r:
            return
        row = r["row"]
        px, py = row.winfo_pointerxy()
        x, y = row.winfo_rootx(), row.winfo_rooty()
        if x <= px < x + row.winfo_width() and y <= py < y + row.winfo_height():
            return
        self._hover_row(action, False)

    def _pick_row(self, action):
        # 捕获期间点别的行直接忽略,免得连点几下把 _capturing 改到另一项上
        if self._capturing:
            return
        self._begin_capture(action)
        self._hotkey_hint.set("请按下新键… (Esc 取消)")

    def _close_hotkey_window(self):
        # 关窗前把输入框里没提交的打字落定,别丢(比如打了「200」还没回车就点 ✕)
        self._commit_editing_entry()
        self._capturing = None
        self._hotkey_rows = {}
        self._hotkey_hint = None
        if self._hotkey_win and self._hotkey_win.winfo_exists():
            self._hotkey_win.destroy()
        self._hotkey_win = None
        self._update_status_label()

    def _refresh_hotkey_list(self):
        """把 config.ini 里当前的键刷到键帽上(改完键 / 重载配置都走这里)。

        **只管文字和字体** —— 颜色(含"未绑定"的暗色)统一归
        _paint_capture_state 一处管,免得两边各写一份、又不一致。
        """
        for action, r in self._hotkey_rows.items():
            if not r["chip_text"].winfo_exists():
                continue
            key = self.cfg.get("Hotkeys", action) or ""
            # MOUSE_LEFT -> 鼠标左键。只是显示,配置里存的还是规范写法。
            text = SPEC_DISPLAY.get(key, key) if key else "(未绑定)"
            r["chip_text"].config(text=text, font=_chip_font(text))
        self._paint_capture_state()

    def _paint_capture_state(self):
        """按 self._capturing 把所有行整体重画一遍(含键帽配色)。

        做成"整体重画"而不是"记住上一行、用完改回去",是因为捕获有三个出口
        —— 改成功 / Esc 取消 / 8 秒超时 —— 分散去改状态,漏掉任何一个,
        高亮就永远钉在某一行上了。整体重画天然不会失同步,而且总共只有 9 行。
        """
        for action, r in self._hotkey_rows.items():
            if not r["row"].winfo_exists():
                continue
            cap = (self._capturing == action)
            bound = bool(self.cfg.get("Hotkeys", action))
            r["row"].config(bg=HK_CAP_BG if cap else HK_BG)
            # 竖条颜色跟着行底色走(而不是写死 HK_BG):这一行可能正被鼠标悬停着,
            # 写死会在悬停的行上留一条 3px 的深色缝
            r["marker"].config(bg=HK_ACCENT if cap else r["row"].cget("bg"))
            r["name"].config(bg=HK_CAP_BG if cap else HK_BG,
                             fg=HK_ACCENT if cap else HK_TEXT)
            r["chip"].config(bg=HK_ACCENT if cap else HK_BORDER)
            r["chip_text"].config(
                bg=HK_ACCENT if cap else HK_CHIP_BG,
                fg=HK_BG if cap else (HK_CHIP_TEXT if bound else HK_DIM))

    def _reset_position(self):
        """把浮窗挪回默认位置;这一步永远留一个还原点,「恢复上次设置」能精确撤回。

        2026-10-14:起先靠 window_x_prev / window_y_prev 记位置 + 单独的
        「恢复上次位置」;同日晚用户要求「能改的全部设置都要能恢复」,并点名
        「包含的话就把恢复上次位置删了」—— 位置并进整份快照:这里走
        save(force_snapshot=True),快照 = 保存前的整份配置 = **点重置前
        一瞬间**的状态,连位置带字号透明度一起,精确撤回(见 Config.save)。
        已经在默认位置再点 = 什么都没发生,那次保存**不强制**刷快照 ——
        免得白丢当前一段调整的还原点。
        """
        cur = (self.cfg.get_int("Display", "window_x"),
               self.cfg.get_int("Display", "window_y"))
        default_pos = (int(DEFAULTS["Display"]["window_x"]),
                       int(DEFAULTS["Display"]["window_y"]))
        self._pos = default_pos
        self.cfg.set("Display", "window_x", self._pos[0])
        self.cfg.set("Display", "window_y", self._pos[1])
        self.cfg.save(force_snapshot=(cur != default_pos))
        self._relayout()
        # 快照可能刚建立 —— 托盘里「恢复上次设置」的置灰状态要跟着刷
        self._refresh_tray()
        # 位置真动过才闪「已重置」—— _tick 每秒刷状态栏,实际只亮 ~1 秒;
        # 已经在默认位置再点 = 没重置,照旧提示「已在默认位置」。
        # 2026-10-14 晚用户要求:原「已重置位置,可恢复」太长,缩短成「已重置」
        # (和「恢复上次设置」闪「已恢复」是同一批改动)。
        self.status_label.config(
            text="已重置" if cur != default_pos else "已在默认位置")
        self.root.after(1500, self._update_status_label)

    def _prev_settings_path(self):
        """1 号快照(最新那份)的路径;托盘「恢复上次设置」的置灰就看它在不在。"""
        return _prev_slot_path(self.cfg.path, 1)

    def _restore_settings(self):
        """整份设置往回退一层(托盘点一次退一层,最多 CONFIG_PREV_SLOTS 层)。

        快照 = config.ini 旁边五槽轮转的历史(config.prev.ini ~ config.prev5.ini,
        见 Config.save),每份 = 某"一段调整"开始前的整份配置。退到哪层看
        Config.restore_depth(每次成功回退 +1,任何保存清零 = 回到"现在");
        逐字节和当前一样的槽位自动跳过 —— 重启后正停在某层、或退回后同段重复
        保存都可能产生这种重复槽,退它屏幕上看不出变化,像点了没反应。连点 =
        一层层往回退,撞到底提示「没有更早的设置」。退回后置 pending_snapshot:
        再动手改的第一次保存会先把"退回的状态"留成新快照,不会白退。
        """
        path = self.cfg.path
        try:
            cur = open(path, "rb").read()
        except OSError:
            cur = None
        depth = self.cfg.restore_depth
        while depth < CONFIG_PREV_SLOTS:
            nxt = _prev_slot_path(path, depth + 1)
            if not os.path.exists(nxt):
                break
            try:
                if open(nxt, "rb").read() != cur:
                    break
            except OSError:
                break
            depth += 1              # 这层和现在的设置一模一样,退它没意义,继续往下
        src = _prev_slot_path(path, depth + 1)
        if not os.path.exists(src):
            self.status_label.config(
                text="没有更早的设置" if depth else "还没有可恢复的设置")
            self.root.after(1500, self._update_status_label)
            return
        try:
            shutil.copyfile(src, path)
        except OSError:
            self.status_label.config(text="恢复失败")
            self.root.after(1500, self._update_status_label)
            return
        self.cfg.restore_depth = depth + 1
        self.cfg.pending_snapshot = True
        self._reload_from_disk()
        # 还原换掉了整份配置(编辑模式可能被 _reload_from_disk 进出过),托盘状态跟着刷
        self._refresh_tray()
        # 2026-10-14 晚用户要求:这句太长,就闪「已恢复」(原「已恢复上次设置」)
        self.status_label.config(text="已恢复")
        self.root.after(1500, self._update_status_label)

    # ==================================================================
    # 改键捕获
    # ==================================================================
    def _begin_capture(self, action):
        self._capturing = action
        self._capture_deadline = time.monotonic() + 8.0
        self._paint_capture_state()
        self._update_status_label()

    def _cancel_capture(self):
        self._capturing = None
        self._paint_capture_state()
        if self._hotkey_hint is not None:
            try:
                self._hotkey_hint.set("")
            except tk.TclError:
                pass
        self._update_status_label()

    def _finish_capture(self, spec):
        action = self._capturing
        self._capturing = None
        if not action:
            return
        self.cfg.set("Hotkeys", action, spec)
        self.cfg.save()
        self.hotkeys = self._load_hotkeys()
        self._refresh_hotkey_list()
        if self._hotkey_hint is not None:
            try:
                self._hotkey_hint.set("已设为 {}".format(spec))
            except tk.TclError:
                pass
        self.status_label.config(text="已设为 {}".format(spec))
        self.root.after(1500, self._update_status_label)

    # ==================================================================
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    _ensure_admin()
    SimpleGameTimer().run()
