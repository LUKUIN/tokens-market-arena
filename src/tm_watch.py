# -*- coding: utf-8 -*-
"""Tokens 交易市场 —— 观众席（只读 | 交易终端风格）

显示：账户权益、累计盈亏、保证金水平、目标进度、可贷额度、
持仓表、权益曲线、多货币报价台、活动流（可滚动、不跳回）。

额外提供：
  | 结束相关进程 —— 通知 API 立即退出，随后关闭观众席
"""

import json
import os
import socket
import sys
import tkinter as tk
import time
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import urllib.request

API = "http://127.0.0.1:8734"
HERE = os.path.dirname(os.path.abspath(__file__))

# 单实例锁：占住一个本地端口，进程退出自动释放。
WATCH_LOCK_PORT = 8735
_LOCK_SOCK = None

# 窗口 / 任务栏图标（￥ 符号，多尺寸 ico）
ICO_PATH = os.path.join(HERE, "app.ico")
WARN_ICO = os.path.join(HERE, "warn.ico")

DISCLAIMER_TEXT = """本程序是一个虚构的杠杆交易模拟游戏，仅供娱乐与学习使用。

【虚构声明】
· 游戏中的货币对、行情走势、随机事件、黑天鹅跳空，全部是程序生成的虚构数据
· 与任何真实市场、真实资产无关，不代表任何真实价格或趋势

【不构成建议】
· 本程序不构成任何投资建议、理财建议或交易策略建议
· 请勿把游戏里的任何操作或盈亏结果，套用到真实交易中

【无真实资金】
· 游戏内的 Tokens、借款、利息、爆仓全部是模拟数值
· 不涉及任何真实资金往来，也不会产生真实盈亏

【风险提示】
· 高杠杆交易在现实中风险极高，可能导致本金全部损失
· 本游戏只是把这种风险做了简化呈现，不能作为风险评估依据

【使用须知】
· 请勿将本程序用于任何形式的赌博、诈骗或非法金融活动
· 程序按现状提供，作者不对使用过程中产生的任何后果负责

点击下方「我已阅读并同意」，表示你已理解以上内容。"""


# 字号缩放：窗口越小，字号相对放大。
# 人的观看距离不变，窗口缩小时若字号同比缩小会看不清；
# 所以小窗反而把字抬一点，把省出来的空间让给字号。
_UI_SCALE = {"v": 1.0}


def _fmt_ff(sec):
    """快进额度显示成「X 分 YY 秒」，避免整数分钟截断丢秒。"""
    try:
        sec = int(round(float(sec or 0)))
    except (TypeError, ValueError, OverflowError):
        sec = 0
    if sec < 0:
        sec = 0
    return "%d 分 %02d 秒" % (sec // 60, sec % 60)


def _ui_font_factor(width):
    f = 1.0 + max(0.0, (1920 - int(width)) / 1920.0) * 0.55
    return round(f, 3)


def _apply_ui_scale(win, width):
    f = _ui_font_factor(width)
    _UI_SCALE["v"] = f
    try:
        win.tk.call("tk", "scaling", 1.333 * f)
    except Exception:
        pass
    return f


RESOLUTIONS = [
    (1366, 768, "1366 × 768"),
    (1400, 900, "1400 × 900"),
    (1600, 900, "1600 × 900"),
    (1920, 1080, "1920 × 1080"),
]


def _pick_resolution():
    """开局前先选窗口尺寸，确定后本局不再改变。"""
    root = tk.Tk()
    root.title("选择窗口尺寸 | Tokens 交易市场")
    root.geometry("560x340+640+300")
    root.resizable(False, False)
    root.configure(bg=BG)
    try:
        root.iconbitmap(ICO_PATH)
    except Exception:
        pass
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    root.after(80, lambda: _hide_close_button(root))

    tk.Label(root, text="选择窗口尺寸", bg=BG, fg=TEXT,
             font=(FONT[0], 15, "bold")).pack(anchor="w", padx=26, pady=(18, 2))
    tk.Label(root, text="选一个适合你屏幕的尺寸，开局后不再改变。",
             bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=26)

    picked = {"v": None}

    def choose(v):
        picked["v"] = v
        _UI_SCALE["v"] = _ui_font_factor(v[0])
        root.destroy()

    wrap = tk.Frame(root, bg=BG)
    wrap.pack(fill="both", expand=True, padx=22, pady=12)
    for i, (w, h, text) in enumerate(RESOLUTIONS):
        tk.Button(wrap, text=text, command=lambda w=w, h=h: choose((w, h)),
                  bg=CARD, fg=TEXT, activebackground="#E8F2FC",
                  font=(FONT[0], 11), bd=0, relief="flat",
                  highlightbackground=BORDER, highlightthickness=1,
                  padx=14, pady=12, cursor="hand2").grid(
            row=i // 2, column=i % 2, sticky="ew", padx=5, pady=5)
    wrap.grid_columnconfigure(0, weight=1)
    wrap.grid_columnconfigure(1, weight=1)

    bf = tk.Frame(root, bg=BG)
    bf.pack(side="bottom", fill="x", padx=26, pady=(0, 16))
    tk.Button(bf, text="用默认 1920 × 1080", command=lambda: choose((1920, 1080)),
              bg="#F1F1F1", fg=MUTED, font=FONT_SMALL, bd=0, relief="flat",
              padx=14, pady=7, cursor="hand2").pack(side="left")

    root.mainloop()
    return picked["v"]


def _hide_close_button(win):
    """让标题栏的关闭按钮失效，但保留最小化、最大化与可拉伸（仅 Windows）。

    不能清 WS_SYSMENU：那会把最小化/最大化一起干掉，而用户明确要求保留最小化。
    这里改用系统菜单：删掉 SC_CLOSE 项并把窗口标记为「不可关闭」，
    效果是 X 变灰点不动，Alt+F4 也被 WM_DELETE_WINDOW 拦下，
    但最小化按钮、拖动边框、双击标题栏最大化都照常可用。
    """
    try:
        import ctypes
        win.update_idletasks()
        SC_CLOSE = 0xF060
        MF_BYCOMMAND = 0x00000000
        u = ctypes.windll.user32
        hwnd = win.winfo_id()
        parent = u.GetParent(hwnd)
        target = parent if parent else hwnd
        # 从系统菜单移除「关闭」
        hmenu = u.GetSystemMenu(target, False)
        if hmenu:
            u.DeleteMenu(hmenu, SC_CLOSE, MF_BYCOMMAND)
            u.DrawMenuBar(target)
        win.update_idletasks()
    except Exception:
        pass


def _ask_yesno(parent, title, message, yes="是", no="否", danger=False):
    """无标题栏关闭按钮的确认框：只能用下面两个按钮关掉。

    标准 messagebox 的 X 去不掉，而这里所有窗口都要求「只认按钮」，
    所以自绘一个 Toplevel：禁 X、置顶、grab_set、默认焦点落在「否」。
    """
    win = tk.Toplevel(parent)
    win.title("%s | Tokens 交易市场" % title)
    win.configure(bg=BG)
    win.transient(parent)
    win.resizable(True, True)
    _apply_icon(win)
    win.protocol("WM_DELETE_WINDOW", lambda: None)
    win.after(120, lambda: _hide_close_button(win))
    result = {"v": False}

    # 系统提示音：危险操作用警告音，普通确认用问号音
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND if danger else winsound.MB_ICONQUESTION)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.MessageBeep(0x30 if danger else 0x20)
        except Exception:
            pass

    body = tk.Frame(win, bg=BG)
    body.pack(fill="both", expand=True, padx=22, pady=(18, 8))
    tk.Label(body, text=message, bg=BG, fg=TEXT, font=FONT,
             justify="left", anchor="w", wraplength=460).pack(fill="x")

    bf = tk.Frame(win, bg=BG)
    bf.pack(side="bottom", fill="x", padx=22, pady=(0, 16))

    def _yes():
        result["v"] = True
        win.destroy()

    def _no():
        win.destroy()

    tk.Button(bf, text=yes, command=_yes, bg=(RED if danger else BLUE), fg="white",
              activebackground=("#8B0000" if danger else "#106EBE"), activeforeground="white",
              font=FONT, bd=0, padx=20, pady=5, cursor="hand2").pack(side="left")
    tk.Button(bf, text=no, command=_no, bg="#F1F1F1", fg=TEXT,
              activebackground="#E5E5E5", font=FONT, bd=0, padx=20, pady=5,
              cursor="hand2").pack(side="left", padx=8)

    win.update_idletasks()
    w, h = max(420, win.winfo_reqwidth()), max(180, win.winfo_reqheight())
    # 居中于父窗口。父窗口尚未映射时 rootx/rooty 会是 0，这时退回屏幕居中，
    # 否则弹窗会贴在左上角。
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = y = None
    try:
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        if pw > 50 and ph > 50 and (px > 0 or py > 0):
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
    except Exception:
        pass
    if x is None:
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
    x = max(0, min(x, sw - w))
    y = max(0, min(y, sh - h))
    win.geometry("%dx%d+%d+%d" % (w, h, x, y))
    win.grab_set()
    win.lift()
    win.attributes("-topmost", True)
    win.focus_force()
    parent.wait_window(win)
    return result["v"]


def _apply_icon(win):
    """给窗口设置 ￥ 图标；任务栏与标题栏都会跟随。

    注意必须先用「无 default」的写法：`iconbitmap(default=...)` 只影响此后新建的
    窗口，对已经存在的窗口不生效。
    """
    try:
        win.iconbitmap(ICO_PATH)
        return
    except Exception:
        pass
    try:
        win.iconbitmap(default=ICO_PATH)
    except Exception:
        pass

# Fluent 配色
# 两个全局开关的显示名：与 tm_engine.SPECIAL_FR_NAME / SPECIAL_SLOT_NAME 保持一致。
# 观众席是独立进程、不 import 引擎，所以这里再声明一份，改名字要同时改两处。
FR_NAME = "优惠融资"
SLOT_NAME = "老虎机"
BG = "#F3F3F3"
CARD = "#FFFFFF"
BORDER = "#E1E1E1"
TEXT = "#1A1A1A"
MUTED = "#6B6B6B"
BLUE = "#0078D4"
GREEN = "#107C10"
RED = "#C42B1C"
ORANGE = "#CA5010"
YELLOW = "#B8860B"
PURPLE = "#7B2FBE"   # 紫：欠款区（净值 < 0）
HEAD = "#F7F7F7"
TOPBAR = "#11213E"   # Fluent 深色标题栏

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TINY = ("Microsoft YaHei UI", 8)
FONT_BIG = ("Microsoft YaHei UI", 23, "bold")
FONT_MID = ("Microsoft YaHei UI", 12, "bold")
FONT_BAR = ("Microsoft YaHei UI", 11)   # 状态条：11pt，比正文小一号但比原 9pt 明显可读
# 难度档位 → 展示用数值（与 tm_engine.GAP_LEVELS / LIQ_LEVELS 保持一致）
_GAP_PCT = {"极低": "0.24%", "低": "0.60%", "中": "1.50%", "高": "3.75%", "极高": "9.38%"}
_LIQ_PCT = {"充裕": "3.5%", "正常": "7.0%", "纤薄": "14.0%", "枯竭": "28%", "黑洞": "56%"}
FONT_LOG = ("Microsoft YaHei UI", 11)   # 活动流专用：比状态栏大一号，便于扫读
FONT_MONO = ("Consolas", 9)
FONT_MONO_BIG = ("Consolas", 11, "bold")

PAIR_ORDER = ["AURA/CORE", "FROST/CORE", "AMBER/CORE", "TIDE/CORE",
              "LUMEN/CORE", "NEON/CORE", "ASH/CORE"]
PAIR_COLORS = {
    "AURA/CORE": "#0078D4", "FROST/CORE": "#107C10", "AMBER/CORE": "#C42B1C",
    "TIDE/CORE": "#8764B8", "LUMEN/CORE": "#CA5010", "NEON/CORE": "#0F7B6C",
    "ASH/CORE": "#8E562E",
}


def get(path):
    with urllib.request.urlopen(API + path, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload=None):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def card(parent, pad=0):
    return tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)


def _fit_title(name, limit=44):
    """标题栏宽度有限：超长时保留首尾、中间省略，避免把「Agent」这种尾巴切掉。"""
    if len(name) <= limit:
        return name
    head = name[:limit // 2]
    tail = name[-(limit // 2 - 1):]
    return head + "…" + tail


class Watch:
    def __init__(self, size=(1920, 1080)):
        self.root = tk.Tk()
        self.root.title("Tokens 交易市场")
        self.W, self.H = int(size[0]), int(size[1])
        self.S = self.W / 1920.0
        # 字号放大后内容变高，窄屏要靠收紧竖向留白把版面塞回可视区
        self.V = 1.0 if self.H >= 1000 else (0.84 if self.H >= 860 else 0.72)
        # 首次开局顺序：难度盲盒 → 规则窗 → 主 GUI。
        # 所以主窗口先隐藏，走完前两步再 deiconify。
        self.root.withdraw()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        px = max(0, (sw - self.W) // 2)
        py = max(0, (sh - self.H) // 2 - 30)
        self.root.geometry("%dx%d+%d+%d" % (self.W, self.H, px, py))
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        # 字号：窗口越小越大（不随窗口同比缩小），保证小窗也能看清
        _apply_ui_scale(self.root, self.W)
        _apply_icon(self.root)
        # 主窗口不允许关闭：关掉就没有 GUI 了，进程还在后台空转。
        # 只留最小化（工具栏那颗按钮），退出走「结束并结算」。
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.root.after(120, lambda: _hide_close_button(self.root))

        self.curve = []
        self.prices = {}
        self.price_history = {}
        self._closing = False
        self._last_trader = None
        self._last_audit = None
        self._log_seen = set()
        self._log_anchor_init = False
        self._last_tick = -1
        self.st = None
        self._tp = None
        # 窄屏放不下活动流：主窗口不建，改由工具栏按钮开独立窗口
        # 只有 1920x1080 走完整版式；1366x768 / 1400x900 / 1600x900 都算窄屏
        self.narrow = self.H <= 900
        self._loan_win = None
        self._loan_left = None
        self.log_text = None
        self._log_win = None

        self._build()
        self.refresh()
        self.root.after(600, self._maybe_show_rules)

    # ------------------------------------------------------------ 布局
    def _build(self):
        root = self.root

        # ---------- 顶栏（Fluent 深色标题栏）----------
        # 深色条把「身份 / 模式 / 全局状态」与正文分开；正文继续用浅色卡片，
        # 层次靠色差就够了，不依赖 Tk 做不出的圆角与阴影。
        topbar = tk.Frame(root, bg=TOPBAR)
        topbar.pack(fill="x")

        _brand = tk.Frame(topbar, bg=TOPBAR)
        _brand.pack(side="left", padx=(18, 0), pady=10)
        tk.Label(_brand, text="TOKENS 交易市场", font=(FONT[0], 12, "bold"),
                 bg=TOPBAR, fg="#FFFFFF").pack(side="left")
        self.lbl_trader = tk.Label(_brand, text="", font=(FONT[0], 11, "bold"),
                                   bg=TOPBAR, fg="#8CC4F8")
        self.lbl_trader.pack(side="left", padx=(14, 0))
        self.lbl_mode = tk.Label(_brand, text="", font=FONT_SMALL, bg=TOPBAR, fg="#AEBBD0")
        self.lbl_mode.pack(side="left", padx=(8, 0))
        tk.Label(_brand, text="投资终端", font=FONT_SMALL,
                 bg=TOPBAR, fg="#7E8CA3").pack(side="left", padx=(10, 0))

        self._f_on = tkfont.Font(root=root, family=FONT[0], size=10, weight="bold")
        self._f_off = tkfont.Font(root=root, family=FONT[0], size=10, weight="bold",
                                  overstrike=1)
        self.lbl_fr = tk.Label(topbar, text=FR_NAME, font=self._f_off,
                               bg=TOPBAR, fg="#D6DFEC")
        self.lbl_fr.pack(side="left", padx=(22, 0))
        self.lbl_slot = tk.Label(topbar, text="老虎机", font=self._f_off,
                                 bg=TOPBAR, fg="#D6DFEC")
        self.lbl_slot.pack(side="left", padx=(10, 0))
        self._last_special = None
        self.btn_slot = tk.Button(topbar, text="老虎机", command=self._open_slot,
                                  font=FONT_SMALL, bd=0, padx=12, pady=4,
                                  bg="#2B3E5C", fg="#C9B8EE", activebackground="#36506F",
                                  activeforeground="#FFFFFF", cursor="hand2")

        btn_style = dict(font=FONT_SMALL, bd=0, relief="flat", cursor="hand2",
                         padx=12, pady=4)
        tk.Button(topbar, text="最小化", command=self.root.iconify,
                  bg="#1E3050", fg="#D5DFEC", activebackground="#2B3E5C",
                  activeforeground="#FFFFFF", **btn_style).pack(side="right", padx=(0, 8), pady=8)
        tk.Button(topbar, text="投资界面", command=self._open_trade_panel,
                  bg="#0F6CBD", fg="white", activebackground="#115EA3",
                  activeforeground="white", **btn_style).pack(side="right", padx=(0, 8), pady=8)
        if self.narrow:
            tk.Button(topbar, text="活动流", command=self._open_log_panel,
                      bg="#2B3E5C", fg="#C9B8EE", activebackground="#36506F",
                      activeforeground="#FFFFFF",
                      **btn_style).pack(side="right", padx=(0, 8), pady=8)
        tk.Button(topbar, text="查看规则", command=lambda: self._show_rules(False),
                  bg="#2B3E5C", fg="#A9C8EE", activebackground="#36506F",
                  activeforeground="#FFFFFF", **btn_style).pack(side="right", padx=(0, 8), pady=8)
        tk.Button(topbar, text="结束相关进程", command=self._kill_all,
                  bg="#1E3050", fg="#F2A6A0", activebackground="#2B3E5C",
                  activeforeground="#FFFFFF", **btn_style).pack(side="right", padx=(0, 10), pady=8)

        # ---------- 指标卡 ----------
        metrics = tk.Frame(root, bg=BG)
        metrics.pack(fill="x", padx=14, pady=(10, 6))
        self.lbl_equity = self._metric(metrics, 0, "账户权益（Tokens）", BLUE, "当前账户净值")
        self.lbl_pnl = self._metric(metrics, 1, "累计盈亏", TEXT, "相对初始本金")
        self.lbl_margin = self._metric(metrics, 2, "保证金水平", TEXT, "低于 100% 触发追缴")
        self.lbl_target = self._metric(metrics, 3, "目标进度", BLUE, "距离获胜目标")
        for i in range(4):
            metrics.columnconfigure(i, weight=1, uniform="m")

        # ---------- 状态条 ----------
        bar = card(root)
        bar.pack(fill="x", padx=14, pady=(0, 6))
        self.lbl_loan = tk.Label(bar, text="可贷 Tokens：—", font=FONT, bg=CARD, fg=BLUE)
        self.lbl_loan.pack(side="left", padx=16, pady=7)
        self.lbl_extra = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_extra.pack(side="left", padx=(0, 16))
        self.lbl_target_abs = tk.Label(bar, text="目标 —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_target_abs.pack(side="left", padx=(0, 16))
        self.lbl_stats = tk.Label(bar, text="回撤 — | 夏普 —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_stats.pack(side="left", padx=(0, 16))
        # 账本自检告警位：默认空着，只有 /state 报出问题时才亮红。
        self.lbl_audit = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=RED)
        self.lbl_audit.pack(side="right", padx=16, pady=7)
        # Abnormal exit of the previous run: more important than a normal market event
        self.lbl_abn = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=RED)
        self.lbl_abn.pack(side="right", padx=16, pady=7)
        self.lbl_status = tk.Label(bar, text="等待连接…", font=FONT, bg=CARD, fg=MUTED)
        self.lbl_status.pack(side="right", padx=16, pady=7)

        # ---------- 时间进度条 ----------
        tbar = tk.Frame(root, bg=CARD)
        tbar.pack(fill="x", padx=14, pady=(0, 6))
        self.cv_time = tk.Canvas(tbar, height=6, bg="#EDF0F4", highlightthickness=0, bd=0)
        self.cv_time.pack(fill="x", side="left", expand=True, pady=4)
        self.lbl_time = tk.Label(tbar, text="剩余 —", font=FONT_TINY, bg=CARD, fg=MUTED)
        self.lbl_time.pack(side="left", padx=(10, 12))
        self.cv_time.bind("<Configure>", lambda e: self._draw_time_bar())

        # ---------- 中部：权益曲线（左，主视觉） + 运行状态（右） ----------
        mid = tk.Frame(root, bg=BG)
        mid.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        left = card(mid)
        left.pack(side="left", fill="both", expand=True)
        self._section_title(left, "权益曲线（Tokens）")
        self.equity_canvas = tk.Canvas(left, bg=CARD, height=236, bd=0,
                                       highlightthickness=0)
        self.equity_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # 右栏只放引擎真实给出的状态，不编造没有数据源的指标。
        right = card(mid)
        right.pack(side="left", fill="y", padx=(8, 0))
        right.configure(width=300)
        right.pack_propagate(False)
        self._section_title(right, "运行状态")
        self._panel_rows = {}
        for _key, _title in (
                ("audit", "账本自检"),
                ("gap", "黑天鹅频率"),
                ("liq", "流动性枯竭"),
                ("ff", "快进额度"),
                ("special", "全局事件")):
            _row = tk.Frame(right, bg=CARD)
            _row.pack(fill="x", padx=14, pady=2)
            tk.Label(_row, text=_title, font=FONT_TINY, bg=CARD, fg=MUTED,
                     anchor="w").pack(anchor="w")
            _val = tk.Label(_row, text="—", font=FONT_SMALL, bg=CARD, fg=TEXT,
                            anchor="w", justify="left", wraplength=262)
            _val.pack(anchor="w")
            self._panel_rows[_key] = _val

        # ---------- 持仓明细（全宽） ----------
        hold = card(root)
        hold.pack(fill="x", padx=14, pady=(0, 6))
        self._section_title(hold, "持仓明细")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Tm.Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, font=FONT_SMALL, rowheight=25, borderwidth=0)
        style.configure("Tm.Treeview.Heading", background=HEAD, foreground=MUTED,
                        font=FONT_SMALL, borderwidth=0, relief="flat")
        style.map("Tm.Treeview", background=[("selected", "#BFD9F2")],
                  foreground=[("selected", TEXT)])
        # 持仓表固定 7 行（改版前的高度），行数超出时内部滚动；
        # 行数超过可视行数时，标题行右侧出现「更多」，点开是同步刷新的完整表。
        tree_wrap = tk.Frame(hold, bg=CARD)
        tree_wrap.pack(fill="x", padx=10, pady=(0, 10))
        self.tree_wrap = tree_wrap
        self.tree = ttk.Treeview(
            tree_wrap, columns=("pair", "side", "lots", "leverage", "entry", "price", "margin", "upnl"),
            show="headings", height=7, style="Tm.Treeview", selectmode="none")
        for col, title, width in (
                ("pair", "交易对", 296), ("side", "方向", 48), ("lots", "手数", 64),
                ("leverage", "杠杆", 48), ("entry", "开仓价", 86), ("price", "最新价", 86),
                ("margin", "保证金", 80), ("upnl", "浮动盈亏", 90)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="center")
        self.tree_vbar = tk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_vbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree_vbar.pack(side="right", fill="y")
        self._hold_win = None
        self._hold_tree = None
        self.btn_hold_more = tk.Button(
            hold, text="更多", command=self._show_hold_panel,
            font=FONT_TINY, bd=0, relief="flat", cursor="hand2",
            bg="#EEF4FF", fg=BLUE, activebackground="#DCE8FB",
            activeforeground=BLUE, padx=10, pady=1)

        # 空仓占位：真正没有持仓、也没有近期成交时，收起表格换成一句明确的空状态。
        self.hold_empty = tk.Frame(hold, bg=CARD)
        tk.Label(self.hold_empty, text="◇", font=(FONT[0], 17), bg=CARD,
                 fg="#C2C8D2").pack(pady=(12, 0))
        tk.Label(self.hold_empty, text="当前没有持仓", font=(FONT[0], 11, "bold"),
                 bg=CARD, fg=TEXT).pack(pady=(4, 1))
        tk.Label(self.hold_empty, text="尚未开仓，或所有持仓均已平仓",
                 font=FONT_SMALL, bg=CARD, fg=MUTED).pack()
        self.hold_empty_n = tk.Label(self.hold_empty, text="0 个活跃持仓",
                                     font=FONT_TINY, bg=CARD, fg="#8A94A6")
        self.hold_empty_n.pack(pady=(3, 12))
        self._hold_mode = None

        # ---------- 底部：报价台 + 活动流 ----------
        bottom = card(root)
        bottom.pack(fill="both", expand=True, padx=14, pady=(0, max(4, int(12 * self.V))))
        self._section_title(bottom, "报价台")

        price_grid = tk.Frame(bottom, bg=CARD)
        price_grid.pack(fill="x", padx=12, pady=(0, 8))
        # 4 列均分父宽：窄屏 + 放大字号时，列宽不会被内容挤成 0
        for _c in range(4):
            price_grid.grid_columnconfigure(_c, weight=1, uniform="px")
        self.price_labels = {}
        for idx, sym in enumerate(PAIR_ORDER):
            row, col = divmod(idx, 4)
            cell = tk.Frame(price_grid, bg=CARD)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=4)
            tk.Frame(cell, bg=PAIR_COLORS.get(sym, MUTED), width=3, height=46).pack(side="left")
            inner = tk.Frame(cell, bg=CARD)
            inner.pack(side="left", padx=(7, 0))
            _top = tk.Frame(inner, bg=CARD)
            _top.pack(anchor="w")
            name = tk.Label(_top, text="—", font=FONT_SMALL, bg=CARD, fg=TEXT, anchor="w")
            name.pack(side="left")
            val = tk.Label(_top, text="—", font=FONT_MONO, bg=CARD, fg=MUTED, anchor="w")
            val.pack(side="left", padx=(6, 0))
            # 迷你走势：数据来自 /state 的 price_history（引擎真实记录），不是示意曲线
            spark = tk.Canvas(inner, width=150, height=20, bg=CARD, bd=0,
                              highlightthickness=0)
            spark.pack(anchor="w")
            self.price_labels[sym] = (name, val, spark)

        if self.narrow:
            # 窄屏放不下：活动流改为工具栏「活动流」按钮打开的独立窗口，
            # 由玩家自己点开，不自动弹。
            return

        # ---------- 活动流头部 ----------
        # 人类版没有分类筛选，只有标题（AI 版才有 tab）
        feed_head = tk.Frame(bottom, bg=CARD)
        feed_head.pack(fill="x")
        tk.Label(feed_head, text="活动流", font=FONT, bg=CARD, fg=TEXT, anchor="w",
                 padx=14, pady=max(3, int(7 * self.V))).pack(side="left")
        self.btn_log_more = tk.Button(
            feed_head, text="更多", command=self._show_log_panel,
            font=FONT_TINY, bd=0, relief="flat", cursor="hand2",
            bg="#EEF4FF", fg=BLUE, activebackground="#DCE8FB",
            activeforeground=BLUE, padx=10, pady=1)
        self.btn_log_more.pack(side="right", padx=(0, 12),
                               pady=max(2, int(3 * self.V)))

        log_wrap = tk.Frame(bottom, bg=CARD)
        log_wrap.pack(fill="x", padx=0, pady=(0, 10))
        self.log_text = tk.Text(log_wrap, bg=CARD, fg=MUTED, font=FONT_LOG, bd=0,
                                height=2, insertbackground=TEXT,
                                padx=14, pady=3,
                                wrap="none", state="disabled")
        self._log_win = None
        self._log_panel_text = None
        self.log_vbar = tk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_vbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_vbar.pack(side="right", fill="y")

    def _metric(self, parent, col, title, color, sub=""):
        c = card(parent)
        c.grid(row=0, column=col, sticky="nsew",
               padx=(0, 8) if col < 3 else (0, 0), pady=2)
        tk.Label(c, text=title, font=FONT_SMALL, bg=CARD, fg=MUTED).pack(
            anchor="w", padx=14, pady=(9, 0))
        v = tk.Label(c, text="—", font=FONT_BIG, bg=CARD, fg=color)
        v.pack(anchor="w", padx=14, pady=(0, 9))
        return v

    def _section_title(self, parent, text):
        tk.Label(parent, text=text, font=FONT, bg=CARD, fg=TEXT, anchor="w",
                 padx=14, pady=max(3, int(7 * self.V))).pack(fill="x")

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        try:
            st = get("/state")
            self._render(st)
        except Exception:
            self.lbl_status.config(text="等待服务启动（python startgame.pyc api 127.0.0.1 8734）",
                                   fg=ORANGE)
        self.root.after(300, self.refresh)

    def _draw_time_bar(self):
        """按当前宽度重画时间进度条（窗口缩放时由 <Configure> 触发）。"""
        st = self.st or {}
        try:
            _el = float(st.get("elapsed_seconds") or 0)
            _total = float(st.get("session_minutes") or 45) * 60.0
            _frac = max(0.0, min(1.0, _el / _total)) if _total > 0 else 0.0
            _rem = max(0.0, _total - _el)
            _w = self.cv_time.winfo_width() or 1
            self.cv_time.delete("all")
            if _frac > 0:
                self.cv_time.create_rectangle(
                    0, 0, max(1, int(_w * _frac)), 6,
                    fill="#2D7FF9" if _frac < 0.8 else "#E8743B", outline="")
            self.lbl_time.config(
                text="剩余 %02d:%02d" % (int(_rem) // 60, int(_rem) % 60),
                fg=MUTED if _frac < 0.8 else "#E8743B")
        except Exception:
            pass

    def _render(self, st):
        self.st = st
        trader = st.get("trader") or "访客"
        mode = "已开启随机事件" if st.get("events_on", True) else "理想情况"
        # 抽到的难度也进标题：一眼能看到这局是什么天气
        gap_lv = st.get("gap_level") or ""
        liq_lv = st.get("liq_level") or ""
        diff = ("%s × %s" % (gap_lv, liq_lv)) if (gap_lv and liq_lv) else ""
        rolling = (not st.get("rolled")) and bool(st.get("roll_left"))
        if self._last_trader != (trader, mode, diff, rolling):
            self._last_trader = (trader, mode, diff, rolling)
            self.lbl_trader.config(text="| %s" % trader)
            self.lbl_mode.config(text="（%s）" % mode,
                                 fg=BLUE if st.get("events_on", True) else MUTED)
            title = "Tokens 交易市场 | %s（%s）" % (_fit_title(trader), mode)
            if gap_lv and liq_lv:
                title += " | 黑天鹅频率：%s（%s/tick） | 流动性枯竭程度：%s（%s 往返）" % (
                    gap_lv, _GAP_PCT.get(gap_lv, "?"),
                    liq_lv, _LIQ_PCT.get(liq_lv, "?"))
            elif rolling:
                title += " | 难度抽选中…"
            self._base_title = title
            self.root.title(title)
        # 【优惠融资】开启后，倒计时单独放标题栏（不占状态栏）
        _lbr = st.get("loan_bump_remain")
        _bt = getattr(self, "_base_title", "")
        if _lbr:
            self.root.title(_bt + " | %s 剩余 %d 秒" % (FR_NAME, int(_lbr + 0.999)))
        elif _bt:
            self.root.title(_bt)
        # 全局开关状态：只在变化时重设字体/按钮可见性
        sp = st.get("special") or {}
        _sig = (bool(sp.get("fr")), bool(sp.get("slot")))
        if self._last_special != _sig:
            self._last_special = _sig
            _fr_on, _slot_on = _sig
            _purple = "#7B3FB8"
            self.lbl_fr.config(font=self._f_on if _fr_on else self._f_off,
                               fg=_purple if _fr_on else "#8A97A8")
            self.lbl_slot.config(font=self._f_on if _slot_on else self._f_off,
                                 fg=_purple if _slot_on else "#8A97A8")
            if _slot_on:
                self.btn_slot.pack(side="right", padx=(0, 8), pady=6)
            else:
                self.btn_slot.pack_forget()

        # 账本自检：空数组=恒等式全部成立；非空时把第一条顶到状态条上。
        _audit = st.get("audit") or []
        _sig_a = tuple(_audit)
        if self._last_audit != _sig_a:
            self._last_audit = _sig_a
            if _audit:
                self.lbl_audit.config(
                    text="⚠ 账本告警 %d 项：%s" % (len(_audit), _audit[0]), fg=RED)
            else:
                self.lbl_audit.config(text="", fg=RED)
        _abn = int(st.get("abnormal_exits") or 0)
        self.lbl_abn.config(text=("⚠ 上局异常退出 %d 次" % _abn) if _abn else "")

        eq, pnl = st["equity"], st["pnl"]
        up = pnl >= 0
        self.lbl_equity.config(text="{:,.0f}".format(eq), fg=GREEN if up else RED)
        self.lbl_pnl.config(text="{:+,.0f} ({:+.2f}%)".format(pnl, st["pnl_pct"]),
                            fg=GREEN if up else RED)

        ml = st["margin_level"]
        if ml is None:
            self.lbl_margin.config(text="—", fg=MUTED)
        else:
            color = GREEN if ml >= 200 else (YELLOW if ml >= 100 else (ORANGE if ml >= 50 else RED))
            # Above 1000% show a multiplier instead of a hard-to-read percentage
            self.lbl_margin.config(text=("%.0fx" % (ml / 100.0)) if ml >= 1000 else ("%.0f%%" % ml),
                                   fg=color)

        self.lbl_target.config(text="%.1f%%" % st["target_pct"], fg=BLUE)
        bonus = st.get("target_bonus", 0) or 0
        self.lbl_target_abs.config(
            text="目标 {:,.0f}{}".format(st.get("target", 0),
                                        ("（贷款上浮 +{:,.0f}）".format(bonus) if bonus else "")))

        loan = st["loan"]
        # 现金与净值是两个数：借款会把现金补正、但净值不变（同时加了欠款），
        # 只显示「权益」会让人以为借款没生效
        self.lbl_loan.config(
            text="可贷 {:,.0f}{} | 现金 {:+,.0f}".format(
                loan["limit"],
                ("（%s）" % st["loan_pool_event"]) if st.get("loan_pool_event") else "",
                st["balance"]),
            fg=BLUE if st["balance"] >= 0 else RED)
        mdd = st.get("max_drawdown")
        shp = st.get("sharpe")
        self.lbl_stats.config(
            text="回撤 {} | 夏普 {}".format("—" if mdd is None else "%.2f%%" % mdd,
                                            "—" if shp is None else "%.2f" % shp))
        # 时间进度条 + 实时统计
        self._draw_time_bar()
        try:
            _cn = int(st.get("closed_n") or 0)
            _wn = int(st.get("win_n") or 0)
            _fee = float(st.get("fees") or 0) + float(st.get("swap") or 0)
            self.lbl_stats.config(
                text="回撤 %s | 夏普 %s | %d 笔 · 胜率 %s | 费息 %.0f" % (
                    "—" if mdd is None else "%.2f%%" % mdd,
                    "—" if shp is None else "%.2f" % shp,
                    _cn,
                    ("%.0f%%" % (_wn * 100.0 / _cn)) if _cn else "—",
                    _fee))
        except Exception as exc:
            sys.stderr.write("time bar: %r\n" % (exc,))
        borrowed = st.get("total_borrowed") or 0
        # 「已借」只显示本金（固定），欠款含利息单独一行，避免这个数字一直在涨
        self.lbl_extra.config(text="已借 {:,.0f} | 欠款 {:,.0f} | 利息 {:,.0f} | {:.3f}%/tick".format(
            borrowed, loan["balance"], loan["interest"], loan["rate_pct"]),
            fg=RED if borrowed > 0 else BLUE)

        # 右栏「运行状态」：同样只放引擎真实给出的值，不编造没有数据源的指标。
        if getattr(self, "_panel_rows", None):
            _pr = self._panel_rows
            try:
                _pr["audit"].config(
                    text=("%d 项告警" % len(_audit)) if _audit else "通过（4 条恒等式）",
                    fg=RED if _audit else GREEN)
                _pr["gap"].config(text="%s（%s/tick）" % (
                    gap_lv or "—", _GAP_PCT.get(gap_lv, "?")))
                _pr["liq"].config(text="%s（%s 往返）" % (
                    liq_lv or "—", _LIQ_PCT.get(liq_lv, "?")))
                _f2 = st.get("ff") or {}
                _rm2 = float(_f2.get("remain") or 0)
                _pr["ff"].config(
                    text=_fmt_ff(_rm2))
                _on = [n for n, v in ((FR_NAME, sp.get("fr")), (SLOT_NAME, sp.get("slot"))) if v]
                _pr["special"].config(text="、".join(_on) if _on else "无")
            except Exception as exc:
                sys.stderr.write("panel rows: %r\n" % (exc,))

        state_txt = "正常交易中"
        if st.get("negative_remain") is not None:
            # 资金为负：要么马上借钱，要么这局就结束了，优先级最高
            state_txt = "资金为负·还剩 %d 秒借款，否则结束" % st["negative_remain"]
        elif st.get("tampered"):
            state_txt = "存档被篡改·已重置"
        elif st.get("clock_cheat"):
            state_txt = "时钟被回拨·计时已冻结"
        elif st.get("margin_call_remain") is not None:
            # 追缴是实时紧急状态，优先级高于「未命名启动」这类提示
            state_txt = "追加保证金·还剩 %d tick" % st["margin_call_remain"]
        elif st.get("unnamed"):
            state_txt = "未命名启动·请用启动游戏.bat"
        elif ml is not None and ml < 50:
            state_txt = "保证金水平告急"
        elif st["blowups"] > 0 and ml is None:
            state_txt = "已爆仓 %d 次" % st["blowups"]

        if st["finished"]:
            state_txt = "本局已结束"
            if not self._closing:
                self._closing = True
                self.root.after(3000, self.root.destroy)
        el = int(st.get("elapsed_seconds", 0))
        mm, ss = divmod(el, 60)
        self.lbl_status.config(
            text=("%s | %02d:%02d | 订单 %d" % (state_txt, mm, ss, st["order_count"])
                  + (("  |  " + " ".join(st["active_mods"])) if st.get("active_mods") else "")),
            fg=RED if any(k in state_txt for k in ("告急", "篡改", "回拨", "未命名", "追加保证金", "资金为负")) else MUTED)

        # 持仓表
        for row in self.tree.get_children():
            self.tree.delete(row)
        _pos = st["positions"]
        _recent = []
        if not _pos:
            # 空仓时把最近 2 分钟内成交过的记录贴出来，避免「刚操作完就什么都看不到」
            _now = time.time()
            _recent = [e for e in st.get("events", [])
                       if e["kind"] in ("open", "close")
                       and _now - float(e.get("time", 0)) < 120][-3:]
        # 实际可见行数少于持仓数时才需要「更多」，不写死 7
        try:
            _visible = int(self.tree.cget("height"))
        except Exception:
            _visible = 7
        if len(_pos) > _visible:
            self.btn_hold_more.place(relx=1.0, x=-14, y=8, anchor="ne")
        else:
            self.btn_hold_more.place_forget()

        _mode = "table" if (_pos or _recent) else "empty"
        if getattr(self, "_hold_mode", None) != _mode:
            self._hold_mode = _mode
            if _mode == "table":
                self.hold_empty.pack_forget()
                self.tree_wrap.pack(fill="x", padx=10, pady=(0, 10))
            else:
                self.tree_wrap.pack_forget()
                self.hold_empty.pack(fill="x", padx=10)

        if _pos:
            for p in _pos:
                self.tree.insert("", "end", values=(
                    p["pair"], "多" if p["side"] == "LONG" else "空",
                    "%.0f" % p["lots"], "%dx" % p["leverage"],
                    "%.4f" % p["entry"], "%.4f" % p["price"],
                    "%.0f" % p["margin"], "%+.0f" % p["upnl"]))
        elif _recent:
            self.tree.configure(height=len(_recent) + 1)
            self.tree.insert("", "end", values=(
                "（空仓）最近 %d 笔" % len(_recent), "", "", "", "", "", "", ""))
            for e in reversed(_recent):
                self.tree.insert("", "end", values=(
                    "  [t%d] %s" % (e["tick"], e["text"][:26]), "", "", "", "", "", "", ""))

        # 持仓弹窗跟随刷新（只在窗口还活着时写，避免对已销毁控件操作）
        if getattr(self, "_hold_tree", None) is not None:
            try:
                if self._hold_win is not None and self._hold_win.winfo_exists():
                    t = self._hold_tree
                    for row in t.get_children():
                        t.delete(row)
                    for p in _pos:
                        t.insert("", "end", values=(
                            p["pair"], "多" if p["side"] == "LONG" else "空",
                            "%.0f" % p["lots"], "%dx" % p["leverage"],
                            "%.4f" % p["entry"], "%.4f" % p["price"],
                            "%.0f" % p["margin"], "%+.0f" % p["upnl"]))
                else:
                    self._hold_win = None
                    self._hold_tree = None
            except Exception:
                self._hold_win = None
                self._hold_tree = None

        # 报价台
        hist = st.get("price_history", {})
        # 是否重画走势只看 tick：判断必须放在循环外，
        # 放到循环里会让第一个品种之后的所有品种永远被跳过。
        _fresh = getattr(self, "_spark_tick", None) != st.get("tick")
        if _fresh:
            self._spark_tick = st.get("tick")
        for sym, q in st["prices"].items():
            pair = self.price_labels.get(sym)
            if not pair:
                continue
            name_lbl, val_lbl, spark = pair
            h = hist.get(sym) or []
            base = h[0] if h else q["price"]
            chg = (q["price"] / base - 1) * 100 if base else 0
            arrow = "▲" if chg > 0.0005 else ("▼" if chg < -0.0005 else "·")
            color = GREEN if chg > 0.0005 else (RED if chg < -0.0005 else MUTED)
            name_lbl.config(text="%s  %s" % (sym, q["name"]), fg=TEXT)
            val_lbl.config(text="%.4f  %s %+.2f%%" % (q["price"], arrow, chg), fg=color)
            if _fresh:
                self._draw_spark(spark, h, color)

        # 曲线
        self.curve = st["equity_curve"]
        self._draw_equity()

        # 活动流（只在有新事件时追加，保持滚动位置）
        self._append_log(st.get("events", []))

        # 资金为负：弹一次贷款自救窗口
        self._maybe_ask_loan(st)

    def _maybe_ask_loan(self, st):
        """资金跌到负数时弹一次贷款窗口；倒计时走完由引擎自己结算。"""
        remain = st.get("negative_remain")
        if remain is None:
            if self._loan_win is not None:
                try:
                    self._loan_win.destroy()
                except Exception:
                    pass
                self._loan_win = None
            return
        # 已经在显示：只刷新倒计时
        if self._loan_win is not None:
            try:
                if self._loan_win.winfo_exists():
                    if self._loan_left is not None:
                        self._loan_left.config(text="%d 秒" % int(remain))
                    self._loan_win.title("资金告负 · 是否借款（剩余 %d 秒）" % int(remain))
                    return
            except Exception:
                pass
            self._loan_win = None
        self._open_loan_win(st, int(remain))

    def _open_loan_win(self, st, remain):
        """贷款自救窗口：确认借款继续玩，或直接终止本局。"""
        win = tk.Toplevel(self.root)
        self._loan_win = win
        win.title("资金告负 · 是否借款（剩余 %d 秒）" % remain)
        win.configure(bg=BG)
        win.resizable(True, True)
        _apply_icon(win)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        # 不允许直接叉掉：只有「确认借款」「否，终止游戏」和倒计时三个出口
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.after(80, lambda: _hide_close_button(win))
        try:
            win.grab_set()
        except Exception:
            pass

        cash = float(st.get("balance") or 0)
        # 可借额度在 state()["loan"]["limit"] 里（= 贷款池 − 已借出）
        limit_ = float((st.get("loan") or {}).get("limit") or 0)

        tk.Label(win, text="资金告负", bg=BG, fg=RED,
                 font=(FONT[0], 16, "bold")).pack(anchor="w", padx=24, pady=(18, 2))
        tk.Label(win, text="所持 Tokens 已跌破 0：%.2f" % cash,
                 bg=BG, fg=TEXT, font=(FONT[0], 11)).pack(anchor="w", padx=24)

        info = tk.Frame(win, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        info.pack(fill="x", padx=24, pady=(10, 4))
        tk.Label(info, text="可借额度  %s" % ("{:,.0f}".format(limit_) if limit_ > 0 else "—"),
                 bg=CARD, fg=TEXT, font=FONT).pack(anchor="w", padx=16, pady=(10, 2))
        tk.Label(info, text="借款会补上现金、同时增加欠款，净值不变——它买的是继续下注的保证金。每借一笔：总目标 = 原目标 + 该笔金额 × 比例（1%~100%，随累计借款额上升，借越多比例越高，借完才定）。",
                 bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=16, pady=(0, 10))

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=24, pady=(4, 0))
        tk.Label(bar, text="剩余时间", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self._loan_left = tk.Label(bar, text="%d 秒" % remain, bg=BG, fg=RED,
                                   font=(FONT[0], 13, "bold"))
        self._loan_left.pack(side="left", padx=(8, 0))

        frow = tk.Frame(win, bg=BG)
        frow.pack(fill="x", padx=24, pady=(8, 0))
        tk.Label(frow, text="借款金额", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self._loan_amt = tk.Entry(frow, width=14, font=FONT, bg=CARD, fg=TEXT,
                                  relief="solid", bd=1)
        self._loan_amt.pack(side="left", padx=(8, 0))
        # 默认填「刚好补平到 0」的金额，省得玩家自己算
        default_amt = max(1.0, min(limit_, -cash + 1)) if limit_ > 0 else 0
        if default_amt > 0:
            self._loan_amt.insert(0, "%.0f" % default_amt)
        self._loan_amt.bind("<Return>", lambda _e: self._do_loan_confirm())

        self._loan_msg = tk.Label(win, text="", bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w")
        self._loan_msg.pack(fill="x", padx=24, pady=(6, 0))

        bf = tk.Frame(win, bg=BG)
        bf.pack(fill="x", padx=24, pady=(10, 16))
        tk.Button(bf, text="确认借款", command=self._do_loan_confirm,
                  bg=BLUE, fg="white", activebackground="#106EBE", activeforeground="white",
                  font=(FONT[0], 10, "bold"), bd=0, relief="flat",
                  padx=20, pady=8, cursor="hand2").pack(side="left")
        tk.Button(bf, text="否，终止游戏", command=self._do_loan_abort,
                  bg="#FDEDED", fg=RED, activebackground="#F8D7D7",
                  font=FONT_SMALL, bd=0, relief="flat",
                  padx=16, pady=8, cursor="hand2").pack(side="left", padx=10)

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry("%dx%d+%d+%d" % (
            max(520, w),
            max(260, h),
            self.root.winfo_x() + (self.W - max(520, w)) // 2,
            self.root.winfo_y() + (self.H - max(260, h)) // 2))
        try:
            win.lift()
            win.focus_force()
        except Exception:
            pass

    def _do_loan_confirm(self):
        """校验并提交借款；金额非法或超额度就地提示，不关窗。"""
        if self._loan_win is None:
            return
        try:
            amt = float((self._loan_amt.get() or "").strip())
        except Exception:
            self._loan_msg.config(text="金额必须是数字", fg=RED)
            return
        if amt <= 0:
            self._loan_msg.config(text="金额必须大于 0", fg=RED)
            return
        try:
            r = post("/loan", {"amount": amt})
        except Exception as exc:
            self._loan_msg.config(text="借款失败：%s" % exc, fg=RED)
            return
        if not r.get("ok"):
            self._loan_msg.config(text=str(r.get("error") or "借款失败"), fg=RED)
            return
        self._loan_msg.config(
            text="已借入 %.0f：现金已补正，净值不变（借款同时增加了欠款）" % amt, fg=GREEN)
        try:
            self._loan_win.destroy()
        except Exception:
            pass
        self._loan_win = None

    def _do_loan_abort(self):
        """放弃自救：直接结算本局。"""
        try:
            post("/quit")
        except Exception:
            pass
        if self._loan_win is not None:
            try:
                self._loan_win.destroy()
            except Exception:
                pass
        self._loan_win = None

    def _append_log(self, events):
        if self.log_text is None:
            return
        if not events:
            if self._log_seen:
                self._log_seen.clear()
                self.log_text.config(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.config(state="disabled")
            return
        at_bottom = self.log_text.yview()[1] >= 0.999
        top = self.log_text.yview()[0]
        fresh = []
        for e in events:
            key = (e.get("tick"), e.get("text"))
            if key in self._log_seen:
                continue
            self._log_seen.add(key)
            fresh.append(e)
        if not fresh:
            return
        if len(self._log_seen) > 400:
            self._log_seen.clear()
            for e in events:
                self._log_seen.add((e.get("tick"), e.get("text")))
        self.log_text.config(state="normal")
        # 按事件种类上色：危险→红/橙，机会→蓝，成交→绿，资金→紫，氛围→灰
        kind_color = {
            "blowup": "#8B0000",      # 爆仓：深红
            "stopout": RED,           # 强平：红
            "gap": "#E07000",         # 黑天鹅跳空：橙红
            "news": PURPLE,           # 突发新闻：紫
            "warn": ORANGE,           # 警告（资金告负、异常退出）：橙
            "margin_call": YELLOW,    # 追加保证金：暗金
            "open": BLUE,             # 开仓成交：蓝
            "close": GREEN,           # 平仓成交：绿
            "loan": "#7B2FBE",        # 借贷：紫
            "end": "#444444",         # 本局结束：深灰
            "trader": "#44546A",      # 身份识别：蓝灰
            "info": MUTED,            # 氛围：灰
        }
        # 主窗口只保留最新一条；完整历史在「更多」弹窗里
        self.log_text.delete("1.0", "end")
        e = fresh[-1]
        k = e.get("kind", "info")
        self.log_text.tag_config(k, foreground=kind_color.get(k, MUTED))
        self.log_text.insert("end", "[t%d] %s\n" % (e["tick"], e["text"]), k)
        if at_bottom:
            self.log_text.see("end")
        else:
            self.log_text.yview_moveto(top)
        self.log_text.config(state="disabled")

    def _show_log_panel(self):
        """完整活动流：独立窗口，自己轮询 /state，关窗后停止刷新。"""
        try:
            if self._log_win is not None and self._log_win.winfo_exists():
                self._log_win.lift()
                return
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        win.title("活动流（全部）")
        win.geometry("920x520")
        win.configure(bg=BG)
        wrap = tk.Frame(win, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=10, pady=10)
        t = tk.Text(wrap, bg=CARD, fg=TEXT, font=FONT_LOG, bd=0, padx=12, pady=8,
                    wrap="none", state="disabled")
        sb = tk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._log_win = win
        self._log_panel_text = t
        win.protocol("WM_DELETE_WINDOW", self._close_log_panel)
        self._refresh_log_panel()

    def _refresh_log_panel(self):
        t = getattr(self, "_log_panel_text", None)
        win = getattr(self, "_log_win", None)
        if t is None or win is None or not win.winfo_exists():
            self._log_win = None
            self._log_panel_text = None
            return
        try:
            st = get("/state")
            evs = st.get("events") or []
            t.config(state="normal")
            t.delete("1.0", "end")
            for e in evs:
                t.insert("end", "[t%d] %s" + chr(92) + "n" % (e["tick"], e["text"]),
                         e.get("kind", "info"))
            t.see("end")
            t.config(state="disabled")
        except Exception:
            pass
        self.root.after(2000, self._refresh_log_panel)

    def _close_log_panel(self):
        try:
            if self._log_win is not None:
                self._log_win.destroy()
        except Exception:
            pass
        self._log_win = None
        self._log_panel_text = None

    def _show_hold_panel(self):
        """持仓明细弹窗：内容跟随主循环刷新，关窗后引用清空。"""
        try:
            if self._hold_win is not None and self._hold_win.winfo_exists():
                self._hold_win.lift()
                return
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        win.title("持仓明细（同步）")
        win.geometry("820x380")
        win.configure(bg=BG)
        t = ttk.Treeview(
            win, columns=("pair", "side", "lots", "leverage", "entry", "price", "margin", "upnl"),
            show="headings", height=12, style="Tm.Treeview", selectmode="none")
        for col, title, width in (
                ("pair", "交易对", 196), ("side", "方向", 50), ("lots", "手数", 62),
                ("leverage", "杠杆", 62), ("entry", "开仓价", 88), ("price", "最新价", 88),
                ("margin", "保证金", 88), ("upnl", "浮动盈亏", 104)):
            t.heading(col, text=title)
            t.column(col, width=width, anchor="center")
        sb = tk.Scrollbar(win, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)
        sb.pack(side="right", fill="y", padx=(0, 12), pady=12)
        self._hold_win = win
        self._hold_tree = t
        win.protocol("WM_DELETE_WINDOW", self._close_hold_panel)

    def _close_hold_panel(self):
        try:
            if self._hold_win is not None:
                self._hold_win.destroy()
        except Exception:
            pass
        self._hold_win = None
        self._hold_tree = None

    def _draw_spark(self, c, hist, color):
        """报价台的迷你走势：只取最近一段真实价格，不足 2 个点就不画。"""
        c.delete("all")
        pts = hist[-48:]
        if len(pts) < 2:
            return
        w, h = 150, 20
        lo, hi = min(pts), max(pts)
        span = hi - lo
        if span <= 0:
            span = 1.0
        n = len(pts)
        coords = []
        for i, v in enumerate(pts):
            coords.append(2 + (w - 4) * i / (n - 1))
            coords.append(h - 3 - (h - 6) * (v - lo) / span)
        c.create_line(*coords, fill=color, width=1.4)

    def _draw_equity(self):
        c = self.equity_canvas
        c.delete("all")
        w = max(c.winfo_width(), 100)
        h = max(c.winfo_height(), 100)
        if len(self.curve) < 2:
            c.create_text(w / 2, h / 2, text="暂无数据", fill=MUTED, font=FONT)
            return

        eqs = [p["equity"] for p in self.curve]
        # 固定刻度：以 50 万为步长。0 / 100 万（本金）/ 200 万（目标）都正好落在刻度上，
        # 负值同样按 50 万向下延伸。刻度数超过 12 条时才退回自适应，避免一屏几十条线。
        _STEP = 500_000.0
        _BASE = 1_000_000.0
        _TARGET = 2_000_000.0
        _vmin = min(min(eqs), 0.0)
        _vmax = max(max(eqs), _BASE, _TARGET)
        lo = (int(_vmin // _STEP) - 1) * _STEP
        hi = (int(_vmax // _STEP) + 1) * _STEP
        _flat = (max(eqs) - min(eqs)) < 0.5
        if (hi - lo) / _STEP > 12:
            _vmin2 = min(eqs)
            _vmax2 = max(eqs)
            _sp = (_vmax2 - _vmin2) or 1.0
            lo = _vmin2 - _sp * 0.10
            hi = _vmax2 + _sp * 0.10
        pad_l, pad_r, pad_t, pad_b = 96, 18, 16, 26
        n = len(eqs)

        def xy(i, v):
            x = pad_l + (w - pad_l - pad_r) * (i / (n - 1))
            y = h - pad_b - (h - pad_t - pad_b) * ((v - lo) / (hi - lo))
            return (x, y)

        # 水平网格 + 刻度
        # 固定 50 万步长；超过 12 条时退回 5 等分自适应
        _span = hi - lo
        if _span / _STEP <= 12:
            _vals = []
            _v = lo
            while _v <= hi + 1e-9:
                _vals.append(_v)
                _v += _STEP
        else:
            _vals = [lo + _span * i / 4 for i in range(5)]
        for v in _vals:
            _, gy = xy(0, v)
            c.create_line(pad_l, gy, w - pad_r, gy, fill="#EEEEEE")
            c.create_text(pad_l - 8, gy, text="{:,.0f}".format(v), anchor="e",
                          fill=MUTED, font=FONT_TINY)
        if _flat:
            c.create_text(w / 2, pad_t + 16, text="暂无资产变化，等待首次交易",
                          fill=MUTED, font=FONT_TINY)

        # 初始资金虚线
        if lo <= 1_000_000 <= hi:
            _, by = xy(0, 1_000_000)
            c.create_line(pad_l, by, w - pad_r, by, fill="#B9B9B9", dash=(4, 4))
            c.create_text(w - pad_r, by - 9, text="初始 1,000,000", fill="#9A9A9A",
                          anchor="e", font=FONT_TINY)

        pts = [xy(i, v) for i, v in enumerate(eqs)]
        color = GREEN if eqs[-1] >= eqs[0] else RED

        # 面积填充（stipple 模拟半透明）
        poly = [pts[0][0], h - pad_b] + [v for p in pts for v in p] + [pts[-1][0], h - pad_b]
        c.create_polygon(*poly, fill=color, stipple="gray12", outline="")

        # 主折线：0 以上沿用绿/红，跌到 0 以下整段转紫（欠款）
        for i in range(n - 1):
            seg = PURPLE if min(eqs[i], eqs[i + 1]) < 0 else color
            c.create_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                          fill=seg, width=2)

        # 0 轴（净值穿过 0 时画一条紫线，让"欠款区"有明确边界）
        if lo < 0 < hi:
            _, zy = xy(0, 0)
            c.create_line(pad_l, zy, w - pad_r, zy, fill=PURPLE, dash=(3, 3))
            c.create_text(pad_l - 8, zy, text="0", anchor="e", fill=PURPLE, font=FONT_TINY)

        # 峰值 / 谷值：靠边时切换水平锚点，避免文字被 Canvas 边界裁掉
        imax = max(range(n), key=lambda i: eqs[i])
        imin = min(range(n), key=lambda i: eqs[i])
        # 最低点就是最后一帧时，谷值标注会与左上角的「当前值」重复
        _skip_low = (imin == n - 1)
        if imax != imin:
            for i, txt, col, up, skip in (
                    (imax, "峰 {:,.0f}".format(eqs[imax]), GREEN, True, False),
                    (imin, "谷 {:,.0f}".format(eqs[imin]), RED, False, _skip_low)):
                if skip:
                    continue
                px, py = xy(i, eqs[i])
                if eqs[i] < 0:
                    col = PURPLE
                c.create_oval(px - 3, py - 3, px + 3, py + 3, fill=col, outline="")
                if px > w - 90:
                    anchor = "se" if up else "ne"
                elif px < pad_l + 90:
                    anchor = "sw" if up else "nw"
                else:
                    anchor = "s" if up else "n"
                dx = -6 if "e" in anchor else (6 if "w" in anchor else 0)
                c.create_text(px + dx, py - 12 if up else py + 12, text=txt,
                              fill=col, anchor=anchor, font=FONT_TINY)

        # 当前值
        c.create_text(pad_l + 4, pad_t + 2, text="当前 {:,.0f}".format(eqs[-1]),
                      fill=PURPLE if eqs[-1] < 0 else color, font=FONT_MID, anchor="nw")

    # ------------------------------------------------------------ 游戏规则
    def _ack_path(self):
        return os.path.join(HERE, "data", ".rules_ack")

    def _read_ack(self):
        try:
            with open(self._ack_path(), encoding="utf-8") as fh:
                return (json.load(fh) or {}).get("session_id") or ""
        except Exception:
            return ""

    def _write_ack(self, session_id):
        try:
            os.makedirs(os.path.dirname(self._ack_path()), exist_ok=True)
            with open(self._ack_path(), "w", encoding="utf-8") as fh:
                json.dump({"session_id": session_id, "at": time.time()}, fh)
        except Exception:
            pass

    @staticmethod
    def _rules_text(r, mode=""):
        def g(key, default=""):
            v = r.get(key)
            return v if v else default

        def kv(d):
            return "、".join("%s %s" % (k, v) for k, v in (d or {}).items()) or "—"

        init = r.get("初始资金")
        init_s = "{:,.0f}".format(float(init)) if isinstance(init, (int, float)) else "1,000,000"
        return "\n".join([
            "【目标】",
            "起始资金 %s Tokens。%s" % (init_s, g("目标")),
            "",
            "【怎么赚钱】",
            "· %s，%s" % (g("手数"), g("杠杆")),
            "· 做多：价格涨就赚；做空：价格跌就赚",
            "· 保证金 = 名义价值 ÷ 杠杆；手续费 = %s" % g("手续费"),
            "· 点差：%s" % kv(g("点差")),
            "· 滑点：%s" % g("滑点"),
            "",
            "【会亏钱的地方】",
            "· 黑天鹅：%s（方向随机，止损可能被直接跳过去）" % g("黑天鹅"),
            "· 流动性枯竭：%s（此时下单更贵）" % g("流动性枯竭"),
            "· 隔夜利息（持仓每 tick 扣一次）：%s" % kv(g("隔夜利息")),
            "· 保证金水平：%s" % g("保证金水平"),
            "",
            "【借钱】",
            "| %s" % g("贷款"),
            "· 每借一笔，最终目标会随机上浮 1%~100% —— 救急可以，但目标会更高",
            "· 利息按 tick 复利滚入欠款；还清欠款 = 连本带息还清，不需要单独再还利息",
            "",
            "【两种模式（标题栏括号里写的就是当前模式）】",
            "· 理想情况：关闭全部随机事件，只剩黑天鹅跳空。行情更“干净”，"
            "不会突然冒出额外惩罚，适合新手先熟悉开仓、平仓、加杠杆的手感。",
            "· 已开启随机事件：除黑天鹅外，还会随机触发二十多种临时事件——"
            "流动性枯竭、手续费上调、保证金加倍、点差放大、杠杆上限下调、行情异常拒单等，"
            "每种持续若干 tick 后自动恢复。难度明显更高，也会让原本算好的成本变脸。",
            "· 当前模式：%s" % (mode or "未知"),
            "",
            "【节奏】",
            "· 会话时长 %s，每 %s 一个 tick，行情自动推进" % (g("会话时长"), g("tick 间隔")),
            "· 到点自动结算；也可以自己点「结束并结算」",
            "· 资金变成负数后会弹出贷款窗口，60 秒内不补回 0 以上，本局立即结束",
            "· 每局快进额度共 15 分钟，按 3 次 × 5 分钟（或 5 次 × 3 分钟）切分；每次快进后需强制冷却（2 分钟 / 1.5 分钟），次数用完即禁用",
            "",
            "【操作】",
            "全部在顶栏「投资界面」里完成：开仓 / 平仓 / 借款 / 还款 / 重开一局 / 结束结算",
            "",
            "【货币对】",
            kv(g("货币对")),
            "",
        ])

    def _show_roll(self, then_rules=False, session_id=""):
        """难度盲盒：两行实心黑方格滚动 30 秒，叫停或归零时定档。

        then_rules=True 时，定档并关闭本窗后接规则窗（首次开局的顺序）。
        """
        import tkinter as _tk
        win = _tk.Toplevel(self.root)
        win.title("难度抽选 | Tokens 交易市场")
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        _apply_icon(win)
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.after(120, lambda: _hide_close_button(win))

        _tk.Label(win, text="难度抽选", bg=BG, fg=TEXT,
                  font=(FONT[0], 16, "bold")).pack(anchor="w", padx=24, pady=(18, 2))
        _tk.Label(win, text="30 秒内每 0.1 秒换一个组合 —— 你可以随时叫停，"
                           "也可以等它自己走完。",
                  bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=24)

        box = _tk.Frame(win, bg=CARD)
        box.pack(fill="x", padx=24, pady=(14, 6))
        CW, CH, GAPX, GAPY = 78, 46, 10, 12
        row1 = _tk.Canvas(box, width=CW * 5 + GAPX * 4, height=CH,
                          bg=CARD, highlightthickness=0, bd=0)
        row1.pack(pady=(16, 6))
        row2 = _tk.Canvas(box, width=CW * 5 + GAPX * 4, height=CH,
                          bg=CARD, highlightthickness=0, bd=0)
        row2.pack(pady=(0, 18))

        def draw(cv):
            cv.delete("all")
            for k in range(5):
                x = k * (CW + GAPX)
                cv.create_rectangle(x, 0, x + CW, CH, fill="#1A1A1A", outline="")

        draw(row1); draw(row2)

        lbl_t = _tk.Label(win, text="剩余 30.0 秒", bg=BG, fg=TEXT,
                          font=(FONT[0], 14, "bold"))
        lbl_t.pack(pady=(0, 4))
        lbl_note = _tk.Label(win, text="叫停后才会显示抽到的难度", bg=BG, fg=MUTED,
                             font=FONT_SMALL)
        lbl_note.pack()

        bf = _tk.Frame(win, bg=BG)
        bf.pack(fill="x", padx=24, pady=16)
        state = {"done": False, "left": 30.0}
        stop_btn = _tk.Button(bf, text="叫  停", bg=BLUE, fg="white",
                              activebackground="#106EBE", activeforeground="white",
                              font=(FONT[0], 11, "bold"), bd=0, padx=28, pady=8,
                              cursor="hand2")
        stop_btn.pack(side="left")

        GAP_NAMES = ["极低", "低", "中", "高", "极高"]
        LIQ_NAMES = ["充裕", "正常", "纤薄", "枯竭", "黑洞"]

        def reveal(res):
            draw(row1); draw(row2)
            gi = GAP_NAMES.index(res.get("gap")) if res.get("gap") in GAP_NAMES else 2
            li = (LIQ_NAMES.index(res.get("liq")) if res.get("liq") in LIQ_NAMES else 2)
            for k in range(5):
                x = k * (CW + GAPX)
                fill = "#2D7FF9" if k == gi else "#E8E8E8"
                row1.create_rectangle(x, 0, x + CW, CH, fill=fill, outline="")
                fill = "#2D7FF9" if k == li else "#E8E8E8"
                row2.create_rectangle(x, 0, x + CW, CH, fill=fill, outline="")
            lbl_t.config(text="黑天鹅 %s   ×   流动性 %s" % (res.get("gap", "?"), res.get("liq", "?")))
            lbl_note.config(text="每 tick %.2f%% 跳空 ｜ 20M 名义往返约 %.1f%%" % (
                (res.get("gap_chance") or 0) * 100,
                (res.get("liquidity") or 8e6) and 14.0 * (8e6 / max(1.0, res.get("liquidity") or 8e6))))
            stop_btn.config(text="开始游戏", state="normal", command=_after_roll)

        def tick():
            if state["done"]:
                return
            try:
                st = get("/state")
                left = float(st.get("roll_left") or 0.0)
            except Exception:
                left = max(0.0, state["left"] - 0.1)
            state["left"] = left
            if left <= 0.05:
                state["done"] = True
                try:
                    res = post("/roll/stop")
                except Exception:
                    res = {"gap": "中", "liq": "纤薄", "gap_chance": 0.015, "liquidity": 8e6}
                reveal(res)
                return
            lbl_t.config(text="剩余 %.1f 秒" % left)
            # 每 0.1 秒重画一次黑格（视觉上是「闪烁的实心块」）
            draw(row1); draw(row2)
            win.after(100, tick)

        def _after_roll():
            win.destroy()
            if then_rules:
                # 难度定了才开始计时；规则窗是开赛前的最后一步展示
                try:
                    post("/begin")
                except Exception:
                    pass
                self.root.after(150, lambda: self._show_rules(
                    first_time=True, session_id=session_id))

        def stop():
            if state["done"]:
                return
            state["done"] = True
            try:
                res = post("/roll/stop")
            except Exception:
                res = {"gap": "中", "liq": "纤薄", "gap_chance": 0.015, "liquidity": 8e6}
            reveal(res)

        stop_btn.config(command=stop)
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry("%dx%d+%d+%d" % (w, h,
            self.root.winfo_x() + (max(600, self.root.winfo_width()) - w) // 2,
            self.root.winfo_y() + (max(400, self.root.winfo_height()) - h) // 2))
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)
        win.after(120, tick)

    def _show_rules(self, first_time=False, session_id=""):
        win = tk.Toplevel(self.root)
        win.title("游戏规则 | Tokens 交易市场")
        win.geometry("820x720+380+120")
        win.configure(bg=BG)
        win.transient(self.root)
        _apply_icon(win)
        win.grab_set()
        # 不允许直接叉掉：否则 wait_window 会返回但确认逻辑没跑，
        # 开局会卡在 paused 状态且 rules_ack 不写，后续再启动又是新的死循环。
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.after(80, lambda: _hide_close_button(win))

        tk.Label(win, text="游戏规则", bg=BG, fg=TEXT,
                 font=(FONT[0], 16, "bold")).pack(anchor="w", padx=22, pady=(16, 2))
        sub = ("开始之前先读一遍 —— 读完后点底部的「我已知晓规则」，"
               "游戏才会正式开始计时。"
               if first_time else "规则随时可以回来查看。")
        tk.Label(win, text=sub, bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=22)

        def done():
            if first_time:
                self._write_ack(session_id)   # begin() 已在抽完难度时调过
            win.destroy()
            if first_time:
                try:
                    self.root.deiconify()
                    self.root.lift()
                except Exception:
                    pass

        tk.Button(win, text="我已知晓规则" if first_time else "关闭",
                  command=done, bg=BLUE, fg="white", activebackground="#106EBE",
                  activeforeground="white", font=(FONT[0], 11, "bold"),
                  bd=0, relief="flat", padx=30, pady=9,
                  cursor="hand2").pack(side="bottom", pady=(0, 16))

        wrap = tk.Frame(win, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=22, pady=12)
        txt = tk.Text(wrap, bg=CARD, fg=TEXT, font=FONT, bd=0, padx=18, pady=14,
                      wrap="word", spacing1=2, spacing3=7, cursor="arrow")
        try:
            rules = get("/rules")
        except Exception:
            rules = {}
        if not isinstance(rules, dict):
            rules = {}
        try:
            _st = get("/state")
            _mode = "已开启随机事件" if (_st or {}).get("events_on", True) else "理想情况"
        except Exception:
            _mode = "未知"
        txt.insert("1.0", self._rules_text(rules, _mode))
        txt.config(state="disabled")
        try:
            txt.update_idletasks()
        except Exception:
            pass
        txt.yview_moveto(0.0)
        for _ms in (60, 180, 400):
            win.after(_ms, lambda: txt.yview_moveto(0.0))
        bar = tk.Scrollbar(wrap, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=bar.set)
        txt.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.root.wait_window(win)

    def _maybe_show_rules(self):
        """新的一局开始时，先冻结游戏并让玩家确认规则。"""
        if self._closing:
            return
        try:
            st = get("/state")
        except Exception:
            self.root.after(1200, self._maybe_show_rules)
            return
        if not isinstance(st, dict) or st.get("finished"):
            return
        sid = st.get("session_id") or ""
        if not sid or self._read_ack() == sid:
            # 本局规则已确认过：没有开局流程，直接把主窗口显示出来
            try:
                self.root.deiconify()
            except Exception:
                pass
            return
        if not st.get("paused"):
            try:
                post("/pause")
            except Exception:
                pass
        # 顺序：暂停 → 抽难度 → 看规则 → begin()。
        # 盲盒只走倒计时，不动行情，也不解除暂停。
        try:
            post("/roll/start")
        except Exception:
            pass
        self._show_roll(then_rules=True, session_id=sid)

    # ------------------------------------------------------------ 投资界面
    def _tp_say(self, text, color=MUTED):
        try:
            self._tp_msg.config(text=text, fg=color)
        except Exception:
            pass

    def _tp_set_lev(self, val):
        try:
            self._tp_lev.delete(0, "end")
            self._tp_lev.insert(0, str(val))
        except Exception:
            pass

    def _tp_guard(self):
        """本局已结算时拦截交易操作，避免对着一局结束的游戏继续下单。"""
        if (self.st or {}).get("finished"):
            self._tp_say("本局已结束 —— 点下方「重开一局」开始新的", ORANGE)
            return False
        return True

    def _open_slot(self):
        """老虎机：投入 1~200000 Tokens（不超过当前权益），整局 3 次。"""
        st = self.st or {}
        sp = st.get("special") or {}
        if not sp.get("slot"):
            messagebox.showinfo("老虎机", "本局未开启【老虎机】。" + chr(10)
                                          + "开新局时在启动窗口里选择开启即可。")
            return
        left = sp.get("slot_left")
        if left is not None and left <= 0:
            messagebox.showinfo("老虎机", "本局老虎机次数已用完（%d/%d）。" % (
                sp.get("slot_plays", 0), 3))
            return
        eq = float(st.get("equity") or 0.0)
        win = tk.Toplevel(self.root)
        win.title("老虎机 · Tokens 交易市场")
        _apply_icon(win)
        win.configure(bg=BG)
        w, h = 460, 300
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))
        win.transient(self.root)
        tk.Label(win, text="老虎机", font=FONT_BIG, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(win, text="剩余 %s 次 · 当前权益 %s" % (
            left if left is not None else "—", "{:,.0f}".format(eq)),
            font=FONT_SMALL, bg=BG, fg=MUTED).pack(anchor="w", padx=20)
        tk.Label(win, text="投入金额（1 ~ 200,000，且不超过当前权益）",
                 font=FONT_SMALL, bg=BG, fg=MUTED).pack(anchor="w", padx=20, pady=(14, 4))
        var = tk.StringVar(value="10000")
        ent = tk.Entry(win, textvariable=var, font=FONT, justify="right")
        ent.pack(fill="x", padx=20)
        tip = tk.Label(win, text="80% 无所得 · 15% 返还 5 倍 · 5% 返还 10 倍",
                       font=FONT_TINY, bg=BG, fg=MUTED)
        tip.pack(anchor="w", padx=20, pady=(6, 0))

        def _go():
            try:
                amt = float(var.get().replace(",", "").strip())
            except Exception:
                messagebox.showwarning("老虎机", "请输入数字。", parent=win)
                return
            r = post("/slot", {"amount": amt})
            if not r or not r.get("ok"):
                messagebox.showwarning("老虎机", (r or {}).get("error", "请求失败"), parent=win)
                return
            mult = r.get("mult") or 0
            payout = r.get("payout") or 0.0
            if mult:
                messagebox.showinfo("老虎机", "中奖！%d 倍，返还 %s Tokens。" + chr(10) + "目标上浮 %+.2f%%（%+.0f）。" % (
                    mult, "{:,.0f}".format(payout), r.get("bump_pct") or 0, r.get("bump") or 0),
                    parent=win)
            else:
                messagebox.showinfo("老虎机", "无所得。", parent=win)
            win.destroy()

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=20, pady=14)
        tk.Button(btns, text="投入", command=_go, font=FONT, bd=0, padx=20, pady=6,
                  bg="#6B4E9B", fg="#FFFFFF", activebackground="#5A3F9E",
                  activeforeground="#FFFFFF", cursor="hand2").pack(side="right")
        tk.Button(btns, text="取消", command=win.destroy, font=FONT, bd=0, padx=20, pady=6,
                  bg="#F1F1F1", fg=TEXT, activebackground="#E5E5E5",
                  cursor="hand2").pack(side="right", padx=(0, 10))
        ent.focus_set()
        ent.select_range(0, "end")

    def _open_trade_panel(self):
        tp = getattr(self, "_tp", None)
        if tp is not None:
            try:
                if tp.winfo_exists():
                    tp.lift()
                    tp.focus_force()
                    return
            except Exception:
                pass
        tp = tk.Toplevel(self.root)
        self._tp = tp
        tp.title("投资 | Tokens 交易市场")
        _apply_icon(tp)
        tp.configure(bg=BG)
        # 尺寸跟着主窗口走，且不超出屏幕：小分辨率下字号被放大，
        # 固定 900 宽会把「下单」挤出可视区
        tw = min(max(900, int(self.W * 0.68)), 1180,
                 max(760, self.root.winfo_screenwidth() - 80))
        th = min(max(800, int(self.H * 0.94)), 980,
                 max(620, self.root.winfo_screenheight() - 80))
        tx = max(0, (self.root.winfo_screenwidth() - tw) // 2)
        ty = max(0, (self.root.winfo_screenheight() - th) // 2 - 20)
        tp.geometry("%dx%d+%d+%d" % (tw, th, tx, ty))
        # 不允许点 X 关闭：只认按钮（X 掉的窗口状态不可控，容易留下悬空引用）
        tp.protocol("WM_DELETE_WINDOW", lambda: None)
        tp.after(120, lambda: _hide_close_button(tp))

        # 内容高度随字号变化，可能超过窗口：套一层可滚动 Canvas，
        # 任何分辨率都不会把底部按钮裁掉
        outer = tk.Frame(tp, bg=BG)
        outer.pack(fill="both", expand=True)
        _cv = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        _vb = tk.Scrollbar(outer, orient="vertical", command=_cv.yview)
        _cv.configure(yscrollcommand=_vb.set)
        _cv.pack(side="left", fill="both", expand=True)
        _vb.pack(side="right", fill="y")
        body = tk.Frame(_cv, bg=BG)
        _cwin = _cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: _cv.configure(scrollregion=_cv.bbox("all")))
        _cv.bind("<Configure>", lambda e: _cv.itemconfigure(_cwin, width=e.width))
        _cv.bind_all("<MouseWheel>",
                     lambda e: _cv.yview_scroll(int(-e.delta / 120), "units"))

        self._tp_info = tk.Label(body, text="", bg=BG, fg=TEXT,
                                 font=(FONT[0], 11, "bold"), anchor="w", justify="left")
        self._tp_info.pack(fill="x", padx=14, pady=(12, 2))
        self._tp_msg = tk.Label(body, text="", bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w")
        self._tp_msg.pack(fill="x", padx=14, pady=(0, 2))

        # ---------------- 开仓 ----------------
        ob = card(body)
        ob.pack(fill="x", padx=14, pady=6)
        self._section_title(ob, "开仓")
        f = tk.Frame(ob, bg=CARD)
        f.pack(fill="x", padx=12, pady=(0, 10))

        f.grid_columnconfigure(6, weight=1)
        tk.Label(f, text="交易对", bg=CARD, fg=MUTED, font=FONT_SMALL).grid(
            row=0, column=0, padx=(0, 4), pady=4, sticky="w")
        self._tp_pair = ttk.Combobox(f, values=PAIR_ORDER, state="readonly",
                                     width=13, font=FONT_SMALL)
        self._tp_pair.current(0)
        self._tp_pair.grid(row=0, column=1, padx=(0, 16), pady=4)

        tk.Label(f, text="方向", bg=CARD, fg=MUTED, font=FONT_SMALL).grid(
            row=0, column=2, padx=(0, 4), pady=4, sticky="w")
        self._tp_side = tk.StringVar(value="LONG")
        rf = tk.Frame(f, bg=CARD)
        rf.grid(row=0, column=3, padx=(0, 16), pady=4, sticky="w")
        tk.Radiobutton(rf, text="做多", variable=self._tp_side, value="LONG",
                       bg=CARD, fg=GREEN, font=FONT_SMALL, selectcolor=CARD,
                       activebackground=CARD, cursor="hand2").pack(side="left")
        tk.Radiobutton(rf, text="做空", variable=self._tp_side, value="SHORT",
                       bg=CARD, fg=RED, font=FONT_SMALL, selectcolor=CARD,
                       activebackground=CARD, cursor="hand2").pack(side="left", padx=(8, 0))

        tk.Label(f, text="手数", bg=CARD, fg=MUTED, font=FONT_SMALL).grid(
            row=0, column=4, padx=(0, 4), pady=4, sticky="w")
        self._tp_lots = tk.Entry(f, width=8, font=FONT_SMALL, bg=CARD, fg=TEXT,
                                 relief="solid", bd=1)
        self._tp_lots.insert(0, "10")
        self._tp_lots.grid(row=0, column=5, padx=(0, 16), pady=4)
        self._tp_lots.bind("<Return>", lambda _e: self._tp_do_open())

        tk.Label(f, text="杠杆", bg=CARD, fg=MUTED, font=FONT_SMALL).grid(
            row=0, column=6, padx=(0, 4), pady=4, sticky="w")
        self._tp_lev = tk.Spinbox(f, from_=1, to=1000, width=6, font=FONT_SMALL,
                                  bg=CARD, fg=TEXT, relief="solid", bd=1)
        self._tp_lev.delete(0, "end")
        self._tp_lev.insert(0, "20")
        self._tp_lev.grid(row=0, column=7, padx=(0, 6), pady=4)
        self._tp_lev.bind("<Return>", lambda _e: self._tp_do_open())

        quick = tk.Frame(f, bg=CARD)
        quick.grid(row=1, column=0, columnspan=6, padx=(0, 10), pady=(2, 0), sticky="w")
        for txt, val in (("1x", 1), ("10x", 10), ("50x", 50),
                         ("100x", 100), ("1000x", 1000)):
            tk.Button(quick, text=txt, command=lambda v=val: self._tp_set_lev(v),
                      bg="#F1F1F1", fg=TEXT, font=FONT_TINY, bd=0, padx=6, pady=2,
                      cursor="hand2").pack(side="left", padx=(0, 3))

        tk.Button(f, text="下单", command=self._tp_do_open, bg=BLUE, fg="white",
                  font=FONT_SMALL, bd=0, padx=22, pady=5, cursor="hand2",
                  activebackground="#106EBE", activeforeground="white").grid(
            row=1, column=6, columnspan=4, padx=(0, 0), pady=(2, 0), sticky="e")

        self._tp_hint = tk.Label(ob, text="", bg=CARD, fg=MUTED,
                                 font=FONT_SMALL, anchor="w")
        self._tp_hint.pack(fill="x", padx=12, pady=(0, 8))

        # ---------------- 持仓 ----------------
        pb = card(body)
        pb.pack(fill="both", expand=True, padx=14, pady=6)
        self._section_title(pb, "持仓（点一行后平仓）")
        cols = ("pair", "side", "lots", "leverage", "entry", "price", "upnl")
        self._tp_tree = ttk.Treeview(pb, columns=cols, show="headings", height=6,
                                     style="Tm.Treeview", selectmode="browse")
        for col, title, w in (("pair", "交易对", 160), ("side", "方向", 60),
                              ("lots", "手数", 70), ("leverage", "杠杆", 60),
                              ("entry", "开仓价", 96), ("price", "最新价", 96),
                              ("upnl", "浮动盈亏", 104)):
            self._tp_tree.heading(col, text=title)
            self._tp_tree.column(col, width=w, anchor="center")
        self._tp_tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        bf = tk.Frame(pb, bg=CARD)
        bf.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(bf, text="平掉选中", command=self._tp_do_close, bg="#E8F2FC", fg=BLUE,
                  font=FONT_SMALL, bd=0, padx=14, pady=4, cursor="hand2").pack(side="left")
        tk.Button(bf, text="全部平仓", command=self._tp_do_close_all, bg="#FDEDED", fg=RED,
                  font=FONT_SMALL, bd=0, padx=14, pady=4, cursor="hand2").pack(
            side="left", padx=8)

        # ---------------- 借贷 ----------------
        lb = card(body)
        lb.pack(fill="x", padx=14, pady=6)
        self._section_title(lb, "借贷（随借随还，利息按 tick 计）")
        self._tp_loan = tk.Label(lb, text="", bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w")
        self._tp_loan.pack(fill="x", padx=12)
        lf = tk.Frame(lb, bg=CARD)
        lf.pack(fill="x", padx=12, pady=(4, 10))
        tk.Label(lf, text="金额", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self._tp_amt = tk.Entry(lf, width=14, font=FONT_SMALL, bg=CARD, fg=TEXT,
                                relief="solid", bd=1)
        self._tp_amt.insert(0, "100000")
        self._tp_amt.pack(side="left", padx=6)
        tk.Button(lf, text="借款", command=self._tp_do_loan, bg="#E8F2FC", fg=BLUE,
                  font=FONT_SMALL, bd=0, padx=14, pady=4, cursor="hand2").pack(side="left")
        tk.Button(lf, text="还款", command=self._tp_do_repay, bg="#F1F1F1", fg=TEXT,
                  font=FONT_SMALL, bd=0, padx=14, pady=4, cursor="hand2").pack(
            side="left", padx=8)

        # ---------------- 快进时间 ----------------
        ff = tk.Frame(body, bg=BG)
        ff.pack(fill="x", padx=14, pady=(2, 2))
        tk.Label(ff, text="快进", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self._tp_ff5 = tk.Button(ff, text="快进 5 分钟", command=lambda: self._tp_do_ff(300),
                                 bg="#EEF4FF", fg=BLUE,
                                 activebackground="#DCE8FB", activeforeground=BLUE,
                                 disabledforeground=MUTED,
                                 font=FONT_SMALL, bd=0, padx=14, pady=4, cursor="hand2")
        self._tp_ff5.pack(side="left", padx=(8, 6))
        self._tp_ff3 = tk.Button(ff, text="快进 3 分钟", command=lambda: self._tp_do_ff(180),
                                 bg="#EEF4FF", fg=BLUE,
                                 activebackground="#DCE8FB", activeforeground=BLUE,
                                 disabledforeground=MUTED,
                                 font=FONT_SMALL, bd=0, padx=14, pady=4, cursor="hand2")
        self._tp_ff3.pack(side="left", padx=(0, 8))
        self._tp_ff_hint = tk.Label(ff, text="", bg=BG, fg=MUTED, font=FONT_SMALL)
        self._tp_ff_hint.pack(side="left")

        # ---------------- 底部 ----------------
        bf2 = tk.Frame(body, bg=BG)
        bf2.pack(fill="x", padx=14, pady=(2, 12))
        tk.Button(bf2, text="重开一局", command=self._tp_do_reset, bg="#FFF4E5", fg=ORANGE,
                  font=FONT_SMALL, bd=0, padx=14, pady=5, cursor="hand2").pack(side="left")
        tk.Button(bf2, text="结束并结算", command=self._tp_do_quit, bg="#FDEDED", fg=RED,
                  font=FONT_SMALL, bd=0, padx=14, pady=5, cursor="hand2").pack(
            side="left", padx=8)
        # 标题栏的 X 已被移除，关闭投资界面只能靠这颗按钮
        tk.Button(bf2, text="关闭窗口", command=self._close_trade_panel, bg="#EEF4FF", fg=BLUE,
                  font=FONT_SMALL, bd=0, padx=14, pady=5, cursor="hand2").pack(
            side="right")

        self._tp_refresh()

    def _close_trade_panel(self):
        try:
            self.root.unbind_all("<MouseWheel>")
        except Exception:
            pass
        tp = getattr(self, "_tp", None)
        self._tp = None
        try:
            if tp is not None and tp.winfo_exists():
                tp.destroy()
        except Exception:
            pass

    def _tp_refresh(self):
        tp = getattr(self, "_tp", None)
        if tp is None:
            return
        try:
            if not tp.winfo_exists():
                return
        except Exception:
            return
        st = self.st or {}
        # 快进按钮状态：两档各自的可用性 + 冷却 + 已用记录
        try:
            _p = st.get("ff") or {}
            _remain = float(_p.get("remain") or 0)
            _cool = float(_p.get("cool_left") or 0)
            _recs = _p.get("records") or []
            _used = float(_p.get("used") or 0)
            if _cool > 0:
                _lab = "冷却中 %d 秒" % int(_cool + 0.999)
                self._tp_ff5.config(text="快进 5 分钟", state="disabled", bg="#F0F0F0", fg=MUTED, cursor="arrow")
                self._tp_ff3.config(text="快进 3 分钟", state="disabled", bg="#F0F0F0", fg=MUTED, cursor="arrow")
                self._tp_ff_hint.config(
                    text="%s | 剩余 %s | 已用 %s" % (
                        _lab, _fmt_ff(_remain), _fmt_ff(sum(_recs))),
                    fg=MUTED)
            else:
                if _remain >= 300:
                    self._tp_ff5.config(text="快进 5 分钟", state="normal", bg="#EEF4FF", fg=BLUE, cursor="hand2")
                else:
                    self._tp_ff5.config(text="快进 5 分钟", state="disabled", bg="#F0F0F0", fg=MUTED, cursor="arrow")
                if _remain >= 180:
                    self._tp_ff3.config(text="快进 3 分钟", state="normal", bg="#EEF4FF", fg=BLUE, cursor="hand2")
                else:
                    self._tp_ff3.config(text="快进 3 分钟", state="disabled", bg="#F0F0F0", fg=MUTED, cursor="arrow")
                if _remain <= 0:
                    self._tp_ff_hint.config(
                        text="额度已用完（已用 %s）" % _fmt_ff(sum(_recs)),
                        fg=MUTED)
                else:
                    self._tp_ff_hint.config(
                        text="剩余 %s | 已用 %s" % (
                            _fmt_ff(_remain), _fmt_ff(sum(_recs))),
                        fg=MUTED)
        except Exception as exc:
            sys.stderr.write("ff button refresh: %r" + chr(92) + "n" % (exc,))
        if st:
            try:
                equity = float(st.get("equity") or 0)
                margin = sum(float(p.get("margin") or 0)
                             for p in (st.get("positions") or []))
                ml = st.get("margin_level")
                self._tp_info.config(
                    text="账户权益 %.0f   |   保证金占用 %.0f   |   保证金水平 %s   |   tick %d"
                    % (equity, margin,
                       ("%.1f%%" % float(ml)) if ml is not None else "—",
                       int(st.get("tick") or 0)))
                loan = st.get("loan") or {}
                _limit = float(loan.get("limit") or 0)
                _debt = float(loan.get("balance") or 0)
                _itr = float(loan.get("interest") or 0)
                _ev = st.get("loan_pool_event") or ""
                _ev_s = ("（%s）" % _ev) if _ev else ""
                if _debt > 0:
                    self._tp_loan.config(
                        text="可贷 %.0f%s   |   已借 %.0f   |   累计利息 %.0f（每 tick 按欠款 %.3f%% 滚入本金）"
                        % (_limit, _ev_s, _debt, _itr, float(loan.get("rate_pct") or 0)))
                else:
                    self._tp_loan.config(
                        text="可贷 %.0f%s   |   欠款已结清   |   累计利息 %.0f（早已随欠款一并还清）"
                        % (_limit, _ev_s, _itr))
                # 记住当前选中（pair + 开仓价可唯一标识一笔），重建后恢复。
                # 否则每 400ms 的整表重建会把选中清掉，「平掉选中」永远点不动。
                prev_key = None
                sel = self._tp_tree.selection()
                if sel:
                    v = self._tp_tree.item(sel[0], "values")
                    if v:
                        prev_key = "%s|%s" % (v[0], v[4])
                self._tp_tree.delete(*self._tp_tree.get_children())
                for p in st.get("positions") or []:
                    # state 里的 prices 是 {品种: {"price":..,"name":..}} 结构；
                    # 持仓项本身已带 price / upnl，直接用，不再去解析 dict。
                    entry = float(p.get("entry") or 0)
                    px = float(p.get("price") or entry)
                    lots = float(p.get("lots") or 0)
                    upnl = float(p.get("upnl") or 0)
                    iid = "%s|%.4f" % (p.get("pair"), entry)
                    self._tp_tree.insert("", "end", iid=iid, values=(
                        p.get("pair"), "做多" if p.get("side") == "LONG" else "做空",
                        "%.0f" % lots, "%dx" % int(p.get("leverage") or 1),
                        "%.4f" % entry, "%.4f" % px, "%+.0f" % upnl))
                    if iid == prev_key:
                        self._tp_tree.selection_set(iid)
                # 开仓提示：现价 + 预估占用保证金
                pair = self._tp_pair.get()
                pinfo = (st.get("prices") or {}).get(pair)
                px0 = float(pinfo.get("price") or 0) if isinstance(pinfo, dict) \
                    else float(pinfo or 0)
                if st.get("finished"):
                    self._tp_hint.config(
                        text="本局已结束，点下方「重开一局」开始新的", fg=RED)
                else:
                    try:
                        lots0 = float(self._tp_lots.get().strip() or 0)
                        lev0 = int(float(self._tp_lev.get().strip() or 1))
                    except Exception:
                        lots0, lev0 = 0.0, 1
                    if px0 > 0 and lots0 > 0 and lev0 > 0:
                        self._tp_hint.config(
                            text="%s 现价 %.4f   |   %.0f 手 × %d 倍 → 占用保证金 ≈ %.0f"
                            % (pair, px0, lots0, lev0, lots0 * 1000.0 * px0 / lev0),
                            fg=MUTED)
                    elif px0 > 0:
                        self._tp_hint.config(text="%s 现价 %.4f" % (pair, px0), fg=MUTED)
            except Exception as exc:
                try:
                    sys.stderr.write("tp_refresh error: %r\n" % (exc,))
                    sys.stderr.flush()
                except Exception:
                    pass
        tp.after(400, self._tp_refresh)

    def _tp_do_open(self):
        if not self._tp_guard():
            return
        try:
            pair = self._tp_pair.get()
            side = self._tp_side.get()
            lots = float(self._tp_lots.get().strip() or 0)
            lev = int(float(self._tp_lev.get().strip() or 1))
            r = post("/open", {"pair": pair, "side": side, "lots": lots, "leverage": lev})
            if r.get("ok"):
                pos = r.get("position") or {}
                self._tp_say(
                    "成交：%s %s %.0f 手 @%.4f（%d 倍，占用保证金 %.0f，手续费 %.1f）"
                    % (pair, "做多" if side == "LONG" else "做空", lots,
                       float(pos.get("entry") or 0), lev,
                       float(pos.get("margin") or 0), float(pos.get("fee") or 0)),
                    GREEN)
            else:
                self._tp_say("下单失败：%s" % r.get("error"), RED)
        except Exception as exc:
            self._tp_say("下单失败：%s" % exc, RED)

    def _tp_do_close(self):
        if not self._tp_guard():
            return
        sel = self._tp_tree.selection()
        if not sel:
            self._tp_say("先在持仓表里点选一行，再点「平掉选中」", ORANGE)
            return
        pair = self._tp_tree.item(sel[0], "values")[0]
        try:
            r = post("/close", {"pair": pair})
            if r.get("ok"):
                closed = r.get("closed") or []
                pnl = sum(float(c.get("pnl") or 0) for c in closed)
                fills = " / ".join("%.4f" % float(c.get("fill") or 0) for c in closed)
                self._tp_say("已平仓：%s @%s   盈亏 %+.0f" % (pair, fills, pnl),
                             GREEN if pnl >= 0 else RED)
            else:
                self._tp_say("平仓失败：%s" % r.get("error"), RED)
        except Exception as exc:
            self._tp_say("平仓失败：%s" % exc, RED)

    def _tp_do_close_all(self):
        if not self._tp_guard():
            return
        if not _ask_yesno(self.root, "全部平仓", "将平掉所有持仓，确定吗？", yes="全部平仓", danger=True):
            return
        try:
            r = post("/close_all")
            if r.get("ok"):
                closed = r.get("closed") or []
                pnl = sum(float(c.get("pnl") or 0) for c in closed)
                self._tp_say("已全部平仓（%d 笔），合计盈亏 %+.0f" % (len(closed), pnl),
                             GREEN if pnl >= 0 else RED)
            else:
                self._tp_say("全部平仓失败：%s" % r.get("error"), RED)
        except Exception as exc:
            self._tp_say("全部平仓失败：%s" % exc, RED)

    def _tp_do_loan(self):
        if not self._tp_guard():
            return
        try:
            amt = float(self._tp_amt.get().strip() or 0)
        except Exception:
            self._tp_say("金额必须是数字", RED)
            return
        if amt <= 0:
            self._tp_say("金额必须大于 0", RED)
            return
        # 只讲清机制与范围，不预告本次抽到的比例——随机加成是借款的代价
        if not _ask_yesno(self.root, "确认借款", '借入 %s Tokens？\n\n⚠ 代价：总目标 = 原目标 + 本笔金额 × 比例（1%%~100%%），\n   比例随累计借款额上升（借得越多越高），借完才抽定，借前无法预知。\n\n这不是免费资金，是拿更难的目标换来的续命机会。\n\n确定？' % "{:,.0f}".format(amt)):
            return
        try:
            r = post("/loan", {"amount": amt})
            if r.get("ok"):
                self._tp_say("已借入 %.0f" % amt, GREEN)
            else:
                self._tp_say("借款失败：%s" % r.get("error"), RED)
        except Exception as exc:
            self._tp_say("借款失败：%s" % exc, RED)

    def _tp_do_repay(self):
        if not self._tp_guard():
            return
        try:
            amt = float(self._tp_amt.get().strip() or 0)
            r = post("/repay", {"amount": amt})
            if r.get("ok"):
                self._tp_say("已还款 %.0f" % amt, GREEN)
            else:
                err = r.get("error") or ""
                if "没有欠款" in err:
                    self._tp_say("欠款已结清 —— 累计利息是每 tick 滚进本金的，"
                                 "还清欠款时就一并还掉了，不需要单独再还", GREEN)
                else:
                    self._tp_say("还款失败：%s" % err, RED)
        except Exception as exc:
            self._tp_say("还款失败：%s" % exc, RED)

    def _tp_do_ff(self, sec=300):
        if not self._tp_guard():
            return
        try:
            r = post("/fastforward", {"seconds": sec})
        except Exception as exc:
            self._tp_say("快进失败：%s" % exc, RED)
            return
        if r.get("ok"):
            st = r.get("state") or {}
            p = r.get("ff") or {}
            self._tp_say("已快进 %d 分钟（%d 个 tick），当前 tick %s，权益 %.0f · 剩余额度 %.0f 秒"
                         % (sec // 60, r.get("ticks") or 0, st.get("tick"),
                            float(st.get("equity") or 0), float(p.get("remain") or 0)), GREEN)
            self.st = st
            try:
                self._tp_refresh()
            except Exception:
                pass
        else:
            msg = r.get("error") or "快进失败"
            self._tp_say(msg, RED)
            if "冷却" in msg:
                _ask_yesno(self.root, "快进冷却中",
                           msg + chr(10) + "冷却结束后才能再次快进。", yes="知道了", no="关闭")

    def _tp_do_reset(self):
        if not _ask_yesno(self.root, "重开一局", "将丢弃当前这局进度，直接开始新的一局。\n确定吗？"):
            return
        try:
            r = post("/reset")
            if r.get("ok"):
                self._tp_say("已重开新局", GREEN)
            else:
                self._tp_say("重开失败：%s" % r.get("error"), RED)
        except Exception as exc:
            self._tp_say("重开失败：%s" % exc, RED)

    def _tp_do_quit(self):
        if not _ask_yesno(self.root, "结束并结算",
                                   "将平掉全部持仓、清算贷款并生成报告，\n随后服务和观众席会关闭。确定吗？"):
            return
        try:
            post("/quit")
            self._tp_say("已结算，服务将在 3 秒后退出", GREEN)
        except Exception as exc:
            self._tp_say("结束失败：%s" % exc, RED)

    # ------------------------------------------------------------ 应急按钮
    def _kill_all(self):
        if not _ask_yesno(self.root, "结束相关进程", "将立即停止 Tokens 服务并关闭观众席。\n确定吗？"):
            return
        try:
            post("/shutdown")
        except Exception:
            pass
        self.lbl_status.config(text="正在结束进程…", fg=RED)
        self.root.after(700, self.root.destroy)
        self.root.after(1000, lambda: os._exit(0))

    def run(self):
        self.root.mainloop()


def _acquire_single_instance():
    """同一个游戏目录只允许存在一个观众席。

    用占住本地端口做进程级互斥：绑定成功即拿到锁，进程退出（含被强杀）
    时操作系统自动释放，不会留下需要人工清理的锁文件。
    """
    global _LOCK_SOCK
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", WATCH_LOCK_PORT))
        s.listen(1)
        _LOCK_SOCK = s
        return True
    except OSError:
        return False


def _warn_already_open():
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showwarning("Tokens 交易市场", "已打开观众席！")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _show_disclaimer():
    """启动前的免责声明：必须点「我已阅读并同意」才会继续，标题栏用警告图标。"""
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.333 * _UI_SCALE.get("v", 1.0))
    except Exception:
        pass
    root.title("免责声明 | Tokens 交易市场")
    root.geometry("660x500+500+230")
    root.resizable(True, True)
    root.configure(bg=BG)
    # 不允许点 X 关闭：必须点「我已阅读并同意」或「退出程序」
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    root.after(120, lambda: _hide_close_button(root))
    try:
        root.iconbitmap(WARN_ICO)
    except Exception:
        pass

    tk.Label(root, text="免责声明", bg=BG, fg=TEXT,
             font=(FONT[0], 16, "bold")).pack(anchor="w", padx=26, pady=(20, 2))
    tk.Label(root, text="开始之前请先看一遍。", bg=BG, fg=MUTED,
             font=FONT_SMALL).pack(anchor="w", padx=26)

    agreed = {"v": False}

    def agree():
        agreed["v"] = True
        root.destroy()

    bf = tk.Frame(root, bg=BG)
    bf.pack(side="bottom", fill="x", padx=26, pady=(0, 18))
    tk.Button(bf, text="我已阅读并同意", command=agree, bg=BLUE, fg="white",
              activebackground="#106EBE", activeforeground="white",
              font=(FONT[0], 11, "bold"), bd=0, relief="flat",
              padx=26, pady=9, cursor="hand2").pack(side="left")
    tk.Button(bf, text="退出程序", command=root.destroy, bg="#F1F1F1", fg=MUTED,
              font=FONT_SMALL, bd=0, relief="flat", padx=18, pady=9,
              cursor="hand2").pack(side="left", padx=12)

    wrap = tk.Frame(root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    wrap.pack(fill="both", expand=True, padx=26, pady=12)
    txt = tk.Text(wrap, bg=CARD, fg=TEXT, font=FONT, bd=0, padx=16, pady=12,
                  wrap="word", spacing1=2, spacing3=6, cursor="arrow")
    txt.insert("1.0", DISCLAIMER_TEXT)
    txt.config(state="disabled")
    txt.pack(fill="both", expand=True)

    root.mainloop()
    return agreed["v"]


def main():
    if not _acquire_single_instance():
        _warn_already_open()
        return
    size = _pick_resolution()
    if not size:
        return
    # 免责声明已挪到「开始游戏！.bat」的命令行阶段（在输入名字之前），
    # 这里不再重复弹一次。
    Watch(size).run()


if __name__ == "__main__":
    main()
