# 恐鬼症计时器 · Phasmophobia Timer

一个给《恐鬼症》（Phasmophobia）用的桌面置顶计时器：无边框、半透明，浮在游戏画面上，全局热键在游戏里直接按，不用切窗口。

**Phasmophobia Timer** is a frameless, always-on-top timing overlay for *Phasmophobia* on Windows. It runs three independent timers — a main round timer, a hunt/event timer that also counts the "attack / calm" phase, and a stopwatch — driven entirely by global hotkeys so nothing interrupts the game. Settings live in `%APPDATA%` and survive updates. Built with Python, tkinter and pynput.

> 关键词 / Keywords：恐鬼症、恐鬼症计时器、恐鬼症猎杀计时、Phasmophobia、phasmophobia timer、hunt timer、speedrun timer、游戏计时器、桌面置顶计时器、Windows overlay、Python tkinter

## 功能

- **三个独立计时单元**：主计时器（一局的主计时）、第二计时器（事件计时，顺带算出「进攻 / 平静」）、独立秒表
- **全程全局热键**：`F1` `F2` `T` `R` `F5`、鼠标左右键、空格，游戏全屏里也能响应
- **无边框置顶浮窗**：没有标题栏和关闭按钮，故意不碍事；`F1` / `F3` 可虚化，虚化期间误按不影响计时
- **编辑模式**：托盘菜单里打勾，直接拖动挪位置、滚轮调字号
- **托盘常驻**：右下角幽灵图标，右键出菜单，改完设置即刻生效
- **配置随用户走**：`%APPDATA%\PhasmophobiaTimer\config.ini`，更新只换程序、设置永不重置；最多 5 层快照，托盘「恢复上次设置」可连点逐层回退

## 热键

| 键 | 作用 |
|---|---|
| `F1` | 启用 / 停用（虚化）主计时器 |
| `F2` | 第二计时器：进入「等待左键」/ 计时中点亮 3 秒看一眼 / 点亮时再按一次清零 |
| 鼠标左键 | 启动第二计时器 |
| 鼠标右键 | 主计时器归零并立刻重新开始 |
| 空格 | 暂停 / 继续主计时器 |
| `T` | 启动秒表（归零重跑） |
| `R` | 切换「主计时器 ↔ 秒表」显示 |
| `F3` | 启用 / 停用（虚化）秒表，停用后按 `T` 不会启动 |
| `F5` | 退出程序 |

完整说明见 [使用说明.md](使用说明.md)，逐版改动见 [更新历史.md](更新历史.md)。

## 运行

需要 Windows 10/11 和 Python 3.9+。

```bat
pip install -r requirements.txt
python timer.py
```

程序靠全局热键工作，需要**以管理员身份运行**。

## 打包

```bat
pyinstaller timer.spec
```

产物在 `dist\timer\`，整个文件夹一起分发（`timer.exe` 和 `_internal` 都不能少）。

## 配置

配置存在 `%APPDATA%\PhasmophobiaTimer\config.ini`，**不在程序文件夹**——这样更新程序不会把设置一起换掉。托盘菜单里的「设置…」可以直接改透明度、字号、上限和所有热键，改完自动保存、即刻生效。想彻底恢复默认，删掉这个文件，下次启动自动重建。

## 许可

代码以 MIT 许可证发布，详见 [LICENSE](LICENSE)。

本项目与 Kinetic Games 无关，《恐鬼症》的名称与游戏内素材版权归 Kinetic Games 所有。
