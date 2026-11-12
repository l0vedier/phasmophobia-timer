# 恐鬼症工具 · Phasmophobia Tools

给《恐鬼症》（Phasmophobia）用的桌面置顶浮窗：无边框、半透明、浮在游戏画面上，全局热键在游戏里直接按，不用切窗口。同一个代码库出三个成品，按需下载：

| 成品 | 可执行文件 | 内容 | 配置文件 |
|---|---|---|---|
| **恐鬼症工具**（二合一） | `tools.exe` | 计时器 + 体力条 | `config.ini` |
| **恐鬼症工具-计时器** | `timer.exe` | 只有计时器 | `timer.ini` |
| **恐鬼症工具-体力条** | `stamina.exe` | 只有体力条 | `stamina.ini` |

三套设置各自独立，**三个工具可以同时开、互不干扰**。下载在 Releases：每个成品一个 Release，按需取。

**Phasmophobia Tools** is a frameless, always-on-top overlay for *Phasmophobia* on Windows. It ships as three builds: a combined round timer + stamina bar, a timer-only build, and a stamina-bar-only build. Everything is driven by global hotkeys so nothing interrupts the game. Settings live in `%APPDATA%` and survive updates. Built with Python, tkinter and pynput.

> 关键词 / Keywords：恐鬼症、恐鬼症计时器、恐鬼症体力条、恐鬼症猎杀计时、Phasmophobia、phasmophobia timer、stamina bar、hunt timer、speedrun timer、游戏计时器、桌面置顶计时器、Windows overlay、Python tkinter

## 功能

- **三个独立计时单元**：主计时器（一局的主计时）、第二计时器（事件计时，顺带算出「进攻 / 平静」；用不到可在托盘一键隐藏 + 停用）、独立秒表
- **体力条**：贴在屏幕左下角，读键盘真实按键算剩余体力（三段式圆角块，大小 / 长度可调）
- **触摸板开关**：`F8` 或托盘一键**停用触摸板/触摸屏设备**（鼠标照常，跟插没插鼠标无关），退出程序自动启用回来；要管理员权限，启动时弹一次 UAC
- **全程全局热键**：`F1` `F2` `T` `R` `F3` `F6` `F8`、鼠标左右键、空格，游戏全屏里也能响应
- **无边框置顶浮窗**：没有标题栏和关闭按钮，故意不碍事；可虚化，虚化期间误按不影响计时
- **编辑模式**：托盘菜单里打勾，直接拖动挪位置、滚轮调字号 / 体力条大小
- **托盘常驻**：右下角幽灵图标，右键出菜单，改完设置即刻生效；退出时会把托盘图标一起注销干净
- **配置随用户走**：`%APPDATA%\PhasmophobiaTimer\`，更新只换程序、设置永不重置；最多 5 层快照，托盘「恢复上次设置」可连点逐层回退

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
| `F6` | 退出程序（可在设置里改） |
| `F8` | 停用 / 恢复触摸板（触摸屏）设备：停用后触摸板完全不响应，鼠标不受影响；退出程序时自动恢复（**仅二合一工具，需管理员权限**） |

体力条另有两个键：`F7` 归满（可在设置里改），`W` `A` `S` `D` / `Shift` / `C` 写死（识别移动、跑步、蹲下）。

以上热键都能在托盘菜单「设置…」里改。完整说明见各成品的 `使用说明.md`。

## 运行

需要 Windows 10/11 和 Python 3.9+。

```bat
pip install -r requirements.txt
python entry_tools.py      :: 二合一
python entry_timer.py      :: 只有计时器
python entry_stamina.py    :: 只有体力条
```

程序靠全局热键工作，需要**以管理员身份运行**（首次启动会自己请求提权）。

## 打包

```bat
pyinstaller timer.spec     :: → dist\timer\timer.exe
pyinstaller stamina.spec   :: → dist\stamina\stamina.exe
pyinstaller tools.spec     :: → dist\tools\tools.exe
```

产物是 onedir：整个文件夹一起分发（exe 和 `_internal` 都不能少）。

## 配置

配置存在 `%APPDATA%\PhasmophobiaTimer\`（三个成品各一个 ini，见上表），**不在程序文件夹**——这样更新程序不会把设置一起换掉。托盘菜单里的「设置…」可以直接改透明度、字号、上限、体力条大小和所有热键，改完自动保存、即刻生效。想彻底恢复默认，删掉对应的 ini，下次启动自动重建。

## 许可

代码以 MIT 许可证发布，详见 [LICENSE](LICENSE)。

本项目与 Kinetic Games 无关，《恐鬼症》的名称与游戏内素材版权归 Kinetic Games 所有。
