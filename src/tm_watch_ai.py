# -*- coding: utf-8 -*-
"""Tokens Trading Market — Spectator (read-only | trading-terminal style)

Shows: account equity, cumulative P&L, margin level, target progress, credit line,
positions table, equity curve, multi-currency quotes, event feed (scrollable, no jump-back).

Also provides:
  | End processes — tells the API to exit immediately, then closes the spectator
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

# Single-instance lock: hold one local port; released automatically when the process exits.
WATCH_LOCK_PORT = 8735
_LOCK_SOCK = None

# Window / taskbar icon (yen symbol, multi-size ico)
ICO_PATH = os.path.join(HERE, "app.ico")
WARN_ICO = os.path.join(HERE, "warn.ico")

DISCLAIMER_TEXT = """This program is a fictional leveraged-trading simulation game, for entertainment and learning only.

[Fiction notice]
· The currency pairs, price action, random events and Black Swan gaps in the game are all procedurally generated fictional data
· They are unrelated to any real market or real asset and do not represent any real price or trend

[Not advice]
· This program does not constitute any investment, financial or trading-strategy advice
· Do not apply any in-game action or P&L result to real trading

[No real money]
· Tokens, borrowing, interest and blown-out accounts in the game are all simulated values
· No real funds are involved and no real P&L is produced

[Risk warning]
· High-leverage trading is extremely risky in reality and may wipe out your entire principal
· This game only presents that risk in a simplified form and cannot be used as a basis for risk assessment

[Usage notice]
· Do not use this program for any form of gambling, fraud or illegal financial activity
· The program is provided as is; the author is not liable for any consequence arising from its use

Click "I have read and agree" below to confirm you understand the above.
"""


# Font scaling: the smaller the window, the larger the font.
# Viewing distance stays the same, so shrinking the font with the window makes it unreadable;
# so a small window actually bumps the font up and spends the saved space on type size.
_UI_SCALE = {"v": 1.0}


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


def _hide_close_button(win):
    """Removes the close button in the top-right corner of the title bar (Windows only).

    `WM_DELETE_WINDOW` only makes the click do nothing; the button itself is still drawn there;
    here we clear WS_SYSMENU from the window style so it really disappears.
    """
    try:
        import ctypes
        win.update_idletasks()
        GWL_STYLE = -16
        WS_SYSMENU = 0x00080000
        u = ctypes.windll.user32
        hwnd = win.winfo_id()
        parent = u.GetParent(hwnd)
        target = parent if parent else hwnd
        style = u.GetWindowLongW(target, GWL_STYLE)
        u.SetWindowLongW(target, GWL_STYLE, style & ~WS_SYSMENU)
        u.SetWindowPos(target, 0, 0, 0, 0, 0, 0x0037)  # refresh the window frame
        win.update_idletasks()
    except Exception:
        pass


def _apply_icon(win):
    """Sets the ￥ icon on the window; the taskbar and title bar both follow it.

    Note that the "no default" form must be used first: `iconbitmap(default=...)` only affects
    windows created afterwards, and has no effect on windows that already exist.
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

# Fluent color palette
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
PURPLE = "#7B2FBE"   # purple: debt zone (net value < 0)
HEAD = "#F7F7F7"

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TINY = ("Microsoft YaHei UI", 8)
FONT_BIG = ("Microsoft YaHei UI", 23, "bold")
FONT_MID = ("Microsoft YaHei UI", 12, "bold")
FONT_BAR = ("Microsoft YaHei UI", 11)   # status bar: 11pt
# Difficulty tier -> display value (must match tm_engine.GAP_LEVELS / LIQ_LEVELS)
_GAP_PCT = {"very low": "0.24%", "low": "0.60%", "medium": "1.50%", "high": "3.75%", "very high": "9.38%"}
_LIQ_PCT = {"abundant": "3.5%", "normal": "7.0%", "thin": "14.0%", "drained": "28%", "black hole": "56%"}
FONT_LOG = ("Microsoft YaHei UI", 11)   # event feed: one size up for scanning
FONT_MONO = ("Consolas", 9)
FONT_MONO_BIG = ("Consolas", 11, "bold")

# Event feed quick-filter tabs: (key, label).  "gap" and "liq" share the same
# engine kind "gap", so they are split by the "[Liquidity drained]" text prefix.
# 流动性事件的前缀（英文版 [Liquidity drained]、中文版【流动性枯竭】，
# 两种括号都要覆盖——此前只匹配英文，中文事件全被归进「黑天鹅」）
_LIQ_MARKS = ("[Liquidity drained]", "【流动性枯竭】", "[流动性枯竭]")

LOG_TABS = (
    ("all", "All"),
    ("gap", "Black Swan"),
    ("liq", "Liquidity"),
    ("news", "Random events"),
    ("trade", "Open / Close"),
    ("risk", "Risk"),
)

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
    """Title bar width is limited: when too long, keep head and tail and elide the middle, so a tail like \"Agent\" is not cut off."""
    if len(name) <= limit:
        return name
    head = name[:limit // 2]
    tail = name[-(limit // 2 - 1):]
    return head + "…" + tail


class Watch:
    def __init__(self, size=(1920, 1080)):
        self.root = tk.Tk()
        self.root.title("Tokens Trading Market")
        self.W, self.H = int(size[0]), int(size[1])
        self.S = self.W / 1920.0
        # Bigger fonts make the content taller; narrow screens must tighten vertical padding to fit the layout back into view
        self.V = 1.0 if self.H >= 1000 else (0.84 if self.H >= 860 else 0.72)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        px = max(0, (sw - self.W) // 2)
        py = max(0, (sh - self.H) // 2 - 30)
        self.root.geometry("%dx%d+%d+%d" % (self.W, self.H, px, py))
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        # Font size: smaller window means bigger font (not scaled down with the window), so small windows stay readable
        _apply_ui_scale(self.root, self.W)
        _apply_icon(self.root)
        # The main window cannot be closed: there would be no GUI left while the process idles in the background.
        # Only minimize is allowed (the toolbar button); exit goes through "End and settle".
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.root.after(120, lambda: _hide_close_button(self.root))

        self.curve = []
        self.prices = {}
        self.price_history = {}
        self._closing = False
        self._last_trader = None
        self._log_seen = set()
        self._log_events = []
        self._log_filter = "all"
        self._log_tabs = {}
        self._log_anchor_init = False
        self._last_tick = -1
        self.st = None
        self._tp = None
        # Narrow screens cannot fit the activity feed: skip it in the main window and open it from a toolbar button instead
        # Only 1920x1080 gets the full layout; 1366x768 / 1400x900 / 1600x900 all count as narrow
        self.narrow = False   # AI edition uses a fixed full layout; the feed is inline, no resolution picker
        self._loan_win = None
        self._loan_left = None
        self.log_text = None
        self._log_win = None

        self._build()
        self.refresh()
        # The AI build shows no rules dialog (rules live in README / the /rules endpoint)

    # ------------------------------------------------------------ layout
    def _build(self):
        root = self.root

        # ---------- toolbar ----------
        topbar = tk.Frame(root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        topbar.pack(fill="x", padx=14, pady=(12, 6))

        tk.Label(topbar, text="  Tokens Trading Market", font=(FONT[0], 12, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left", padx=(6, 4), pady=8)
        self.lbl_trader = tk.Label(topbar, text="", font=(FONT[0], 12, "bold"),
                                   bg=CARD, fg=BLUE)
        self.lbl_trader.pack(side="left", padx=(10, 0))
        self.lbl_mode = tk.Label(topbar, text="", font=FONT_SMALL, bg=CARD, fg=MUTED)
        self.lbl_mode.pack(side="left", padx=(8, 0))
        tk.Label(topbar, text="Read-only spectator terminal", font=FONT_SMALL, bg=CARD, fg=MUTED).pack(
            side="left", pady=8)

        # State of the two global switch events: on = purple bold; off = black bold + strikethrough
        self._f_on = tkfont.Font(root=root, family=FONT[0], size=10, weight="bold")
        self._f_off = tkfont.Font(root=root, family=FONT[0], size=10, weight="bold",
                                  overstrike=1)
        self.lbl_fr = tk.Label(topbar, text="Finance Reversal", font=self._f_off,
                               bg=CARD, fg=TEXT)
        self.lbl_fr.pack(side="left", padx=(16, 0), pady=8)
        self.lbl_slot = tk.Label(topbar, text="Slot Machine", font=self._f_off,
                                 bg=CARD, fg=TEXT)
        self.lbl_slot.pack(side="left", padx=(10, 0), pady=8)
        self._last_special = None

        btn_style = dict(font=FONT_SMALL, bd=0, relief="flat", cursor="hand2",
                         padx=12, pady=4)
        tk.Button(topbar, text="AI Notes", command=self._show_scratch,
                  bg="#F3EEFF", fg="#6B4E9B", activebackground="#E9E0FF",
                  activeforeground="#6B4E9B", font=FONT_SMALL, bd=0,
                  padx=14, pady=5, cursor="hand2").pack(side="right", padx=(0, 8), pady=6)
        tk.Button(topbar, text="Minimize", command=self.root.iconify,
                  bg="#F1F1F1", fg=TEXT, activebackground="#E5E5E5",
                  **btn_style).pack(side="right", padx=(0, 8), pady=6)
        tk.Button(topbar, text="End processes", command=self._kill_all,
                  bg="#FDEDED", fg=RED, activebackground="#F8D7D7",
                  activeforeground=RED, **btn_style).pack(side="right", padx=(0, 10), pady=6)

        # ---------- metric cards ----------
        metrics = tk.Frame(root, bg=BG)
        metrics.pack(fill="x", padx=14, pady=(0, 6))
        self.lbl_equity = self._metric(metrics, 0, "Account equity (Tokens)", BLUE)
        self.lbl_pnl = self._metric(metrics, 1, "Cumulative P&L", TEXT)
        self.lbl_margin = self._metric(metrics, 2, "Margin level", TEXT)
        self.lbl_target = self._metric(metrics, 3, "Target progress", BLUE)
        for i in range(4):
            metrics.columnconfigure(i, weight=1, uniform="m")

        # ---------- status bar, row 1: account / capital ----------
        bar = card(root)
        bar.pack(fill="x", padx=14, pady=(0, 4))
        self.lbl_loan = tk.Label(bar, text="Credit Tokens: —", font=FONT, bg=CARD, fg=BLUE)
        self.lbl_loan.pack(side="left", padx=16, pady=7)
        self.lbl_extra = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_extra.pack(side="left", padx=(0, 16))
        self.lbl_status = tk.Label(bar, text="Waiting for connection...", font=FONT, bg=CARD, fg=MUTED)
        self.lbl_status.pack(side="right", padx=16, pady=7)

        # ---------- status bar, row 2: the figures that change every tick ----------
        # Long English sentences made the single band unreadable, so the fast-moving
        # numbers (drawdown / Sharpe / win rate / fees) get their own line.
        bar2 = card(root)
        bar2.pack(fill="x", padx=14, pady=(0, 6))
        self.lbl_target_abs = tk.Label(bar2, text="Target —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_target_abs.pack(side="left", padx=16, pady=5)
        self.lbl_stats = tk.Label(bar2, text="Drawdown — | Sharpe —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_stats.pack(side="left", padx=(0, 16))
        self.lbl_ff = tk.Label(bar2, text="Fast-forward —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_ff.pack(side="right", padx=16, pady=5)

        # ---------- time progress bar ----------
        tbar = tk.Frame(root, bg=CARD)
        tbar.pack(fill="x", padx=14, pady=(0, 6))
        self.cv_time = tk.Canvas(tbar, height=6, bg="#EDF0F4", highlightthickness=0, bd=0)
        self.cv_time.pack(fill="x", side="left", expand=True, pady=4)
        self.lbl_time = tk.Label(tbar, text="Remaining —", font=FONT_TINY, bg=CARD, fg=MUTED)
        self.lbl_time.pack(side="left", padx=(10, 12))
        self.cv_time.bind("<Configure>", lambda e: self._draw_time_bar())
        self._cv_bar = None

        # ---------- middle: positions + curve ----------
        mid = tk.Frame(root, bg=BG)
        mid.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        left = card(mid)
        left.pack(side="left", fill="both", expand=True)
        self._section_title(left, "Positions")

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
        self.tree = ttk.Treeview(
            left, columns=("pair", "side", "lots", "leverage", "entry", "price", "margin", "upnl"),
            show="headings", height=7, style="Tm.Treeview", selectmode="none")
        for col, title, width in (
                ("pair", "Pair", 196), ("side", "Side", 50), ("lots", "Lots", 62),
                ("leverage", "Leverage", 62), ("entry", "Entry", 88), ("price", "Last", 88),
                ("margin", "Margin", 82), ("upnl", "Unrealised P&L", 96)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        right = card(mid)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._section_title(right, "Equity curve (Tokens)")
        self.equity_canvas = tk.Canvas(right, bg=CARD, height=330, bd=0,
                                       highlightthickness=0)
        self.equity_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # ---------- bottom: quote board + activity feed ----------
        bottom = card(root)
        bottom.pack(fill="both", expand=True, padx=14, pady=(0, max(4, int(12 * self.V))))
        self._section_title(bottom, "Quotes")

        price_grid = tk.Frame(bottom, bg=CARD)
        price_grid.pack(fill="x", padx=12, pady=(0, 8))
        # Four columns split the parent width evenly: on narrow screens with big fonts no column gets squeezed to 0
        for _c in range(4):
            price_grid.grid_columnconfigure(_c, weight=1, uniform="px")
        self.price_labels = {}
        for idx, sym in enumerate(PAIR_ORDER):
            row, col = divmod(idx, 4)
            cell = tk.Frame(price_grid, bg=CARD)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 10), pady=2)
            tk.Frame(cell, bg=PAIR_COLORS.get(sym, MUTED), width=3, height=30).pack(side="left")
            inner = tk.Frame(cell, bg=CARD)
            inner.pack(side="left", padx=(7, 0))
            name = tk.Label(inner, text="—", font=FONT_SMALL, bg=CARD, fg=TEXT, anchor="w")
            name.pack(anchor="w")
            val = tk.Label(inner, text="—", font=FONT_MONO, bg=CARD, fg=MUTED, anchor="w")
            val.pack(anchor="w")
            self.price_labels[sym] = (name, val)

        if self.narrow:
            # Narrow screens cannot fit it: the activity feed moves to a separate window opened from the "Activity feed" toolbar button,
            # opened by the player, never popped up automatically.
            return

        # ---------- event feed header with category tabs ----------
        feed_head = tk.Frame(bottom, bg=CARD)
        feed_head.pack(fill="x")
        tk.Label(feed_head, text="Event feed", font=FONT, bg=CARD, fg=TEXT, anchor="w",
                 padx=14, pady=max(3, int(7 * self.V))).pack(side="left")
        tab_box = tk.Frame(feed_head, bg=CARD)
        tab_box.pack(side="right", padx=(0, 12), pady=max(2, int(3 * self.V)))
        for _key, _label in LOG_TABS:
            _btn = tk.Button(tab_box, text=_label, font=FONT_TINY, bd=0, relief="flat",
                             cursor="hand2", padx=9, pady=2,
                             command=lambda k=_key: self._set_log_filter(k))
            _btn.pack(side="left", padx=(0, 4))
            self._log_tabs[_key] = _btn
        self._paint_log_tabs()

        log_wrap = tk.Frame(bottom, bg=CARD)
        log_wrap.pack(fill="both", expand=True, padx=0, pady=(0, 10))
        self.log_text = tk.Text(log_wrap, bg=CARD, fg=MUTED, font=FONT_LOG, bd=0,
                                height=max(3, int(6 * self.V)), insertbackground=TEXT,
                                padx=14, pady=4,
                                wrap="none", state="disabled")
        self.log_vbar = tk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_vbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_vbar.pack(side="right", fill="y")

    def _metric(self, parent, col, title, color):
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

    # ------------------------------------------------------------ refresh
    def refresh(self):
        try:
            st = get("/state")
            self._render(st)
        except Exception:
            self.lbl_status.config(text="Waiting for the service to start (python startgame.pyc api 127.0.0.1 8734)",
                                   fg=ORANGE)
        self.root.after(300, self.refresh)

    def _draw_time_bar(self):
        """Redraws the time progress bar at the current width (triggered by <Configure> on window resize)."""
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
                text="Remaining %02d:%02d" % (int(_rem) // 60, int(_rem) % 60),
                fg=MUTED if _frac < 0.8 else "#E8743B")
        except Exception:
            pass

    def _show_scratch(self):
        """View what the AI wrote in the scratchpad (read-only)."""
        try:
            r = get("/scratchpad")
        except Exception as exc:
            messagebox.showwarning("AI Notes", "Read failed: %s" % exc)
            return
        items = (r or {}).get("items") or []
        win = tk.Toplevel(self.root)
        win.title("AI Notes · Tokens Trading Market")
        win.configure(bg=BG)
        w, h = 760, 620
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        _apply_icon(win)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        tk.Label(win, text="Scratchpad (%d entries)" % len(items), bg=BG, fg=TEXT,
                 font=FONT_BIG).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(win, text="The AI may write its own judgement and counter-measures at any time; this window is read-only.",
                 bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(0, 8))
        wrap = tk.Frame(win, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        txt = tk.Text(wrap, font=FONT_BAR, bg=CARD, fg=TEXT, bd=0,
                      relief="flat", wrap="word", padx=12, pady=10)
        sb = tk.Scrollbar(wrap, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if items:
            for x in items:
                txt.insert("end", "[t%s · %s s]" % (x.get("tick", "—"),
                                                    ("%.0f" % float(x.get("elapsed") or 0))))
                txt.insert("end", chr(10) + str(x.get("text", "")) + chr(10) + chr(10))
        else:
            txt.insert("end", "The AI has not left anything in the scratchpad this session.")
        txt.config(state="disabled")
        txt.yview_moveto(0.0)
        win.after(80, lambda: txt.yview_moveto(0.0))

    def _render(self, st):
        self.st = st
        trader = st.get("trader") or "Guest"
        mode = "Random events on" if st.get("events_on", True) else "Ideal case"
        # Put the drawn difficulty in the title too, matching the human build
        gap_lv = st.get("gap_level") or ""
        liq_lv = st.get("liq_level") or ""
        diff = ("%s × %s" % (gap_lv, liq_lv)) if (gap_lv and liq_lv) else ""
        rolling = (not st.get("rolled")) and bool(st.get("roll_left"))
        if self._last_trader != (trader, mode, diff, rolling):
            self._last_trader = (trader, mode, diff, rolling)
            self.lbl_trader.config(text="| %s" % trader)
            self.lbl_mode.config(text="（%s）" % mode,
                                 fg=BLUE if st.get("events_on", True) else MUTED)
            title = "Tokens Trading Market | %s (%s)" % (_fit_title(trader), mode)
            if gap_lv and liq_lv:
                title += " | Black Swan: %s (%s/tick) | Liquidity: %s (%s round trip)" % (
                    gap_lv, _GAP_PCT.get(gap_lv, "?"),
                    liq_lv, _LIQ_PCT.get(liq_lv, "?"))
            elif rolling:
                title += " | Choosing difficulty..."
            self._base_title = title
            self.root.title(title)
        # [Finance Reversal] keeps draining money until the target is changed, so its countdown goes in the title bar (not the status bar)
        _lbr = st.get("loan_bump_remain")
        _bt = getattr(self, "_base_title", "")
        if _lbr:
            self.root.title(_bt + " | Finance Reversal %d s left" % int(_lbr + 0.999))
        elif _bt:
            self.root.title(_bt)
        # Global switch state (reset fonts only on change; avoid touching widgets on every refresh)
        sp = st.get("special") or {}
        _sig = (bool(sp.get("fr")), bool(sp.get("slot")))
        if self._last_special != _sig:
            self._last_special = _sig
            _fr_on, _slot_on = _sig
            _purple = "#7B3FB8"
            self.lbl_fr.config(font=self._f_on if _fr_on else self._f_off,
                               fg=_purple if _fr_on else TEXT)
            self.lbl_slot.config(font=self._f_on if _slot_on else self._f_off,
                                 fg=_purple if _slot_on else TEXT)

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
            self.lbl_margin.config(text="%.0f%%" % ml, fg=color)

        self.lbl_target.config(text="%.1f%%" % st["target_pct"], fg=BLUE)
        bonus = st.get("target_bonus", 0) or 0
        self.lbl_target_abs.config(
            text="Target {:,.0f}{}".format(st.get("target", 0),
                                        ("(loan markup +{:,.0f})".format(bonus) if bonus else "")))

        loan = st["loan"]
        # Cash and net value are two different numbers: a loan repairs cash but leaves net value unchanged (it adds debt too),
        # showing only "equity" makes loans look like they did nothing
        self.lbl_loan.config(
            text="Credit {:,.0f}{} | Cash {:+,.0f}".format(
                loan["limit"],
                ("（%s）" % st["loan_pool_event"]) if st.get("loan_pool_event") else "",
                st["balance"]),
            fg=BLUE if st["balance"] >= 0 else RED)
        mdd = st.get("max_drawdown")
        shp = st.get("sharpe")
        try:
            _cn = int(st.get("closed_n") or 0)
            _wn = int(st.get("win_n") or 0)
            _fee = float(st.get("fees") or 0) + float(st.get("swap") or 0)
            _stat = "Drawdown %s | Sharpe %s | %d trades · Win rate %s | Fees & interest %.0f" % (
                "—" if mdd is None else "%.2f%%" % mdd,
                "—" if shp is None else "%.2f" % shp,
                _cn,
                ("%.0f%%" % (_wn * 100.0 / _cn)) if _cn else "—",
                _fee)
        except Exception:
            _stat = "Drawdown {} | Sharpe {}".format("—" if mdd is None else "%.2f%%" % mdd,
                                                "—" if shp is None else "%.2f" % shp)
        self.lbl_stats.config(text=_stat)
        # Time progress bar (width-adaptive; redrawn on <Configure> when resized)
        self._draw_time_bar()
        # Fast-forward quota (read-only): remaining + usage log + cooldown
        try:
            _f = st.get("ff") or {}
            _rm = float(_f.get("remain") or 0)
            _cd = float(_f.get("cool_left") or 0)
            _rc = _f.get("records") or []
            _txt = ("Fast-forward %d min left" % int(_rm // 60)) if _rm >= 60 else ("Fast-forward %d s left" % int(_rm))
            if _rc:
                _txt += " | %d min elapsed" % int(sum(_rc) // 60)
            if _cd > 0:
                _txt += " | Cooldown %d s" % int(_cd + 0.999)
            self.lbl_ff.config(text=_txt, fg=RED if _cd > 0 else MUTED)
        except Exception as exc:
            sys.stderr.write("ff label: %r\n" % (exc,))
        borrowed = st.get("total_borrowed") or 0
        # "Borrowed" shows principal only (fixed); interest-bearing debt gets its own line so the number stops creeping up
        self.lbl_extra.config(text="Borrowed {:,.0f} | Owed {:,.0f} | Interest {:,.0f} | {:.3f}%/tick".format(
            borrowed, loan["balance"], loan["interest"], loan["rate_pct"]),
            fg=RED if borrowed > 0 else BLUE)

        state_txt = "Trading normally"
        if st.get("negative_remain") is not None:
            # Negative balance: borrow now or the round is over; highest priority
            state_txt = "Negative equity · %d s left to borrow, otherwise the session ends" % st["negative_remain"]
        elif st.get("tampered"):
            state_txt = "Save tampered · reset"
        elif st.get("clock_cheat"):
            state_txt = "Clock rolled back · timing frozen"
        elif st.get("margin_call_remain") is not None:
            # A margin call is a live emergency; it outranks notices like "unnamed start"
            state_txt = "Margin call · %d ticks left" % st["margin_call_remain"]
        elif st.get("unnamed"):
            state_txt = "Unnamed launch · please use Start Match.bat"
        elif ml is not None and ml < 50:
            state_txt = "Margin level critical"
        elif st["blowups"] > 0 and ml is None:
            state_txt = "Blown out %d times" % st["blowups"]

        if st["finished"]:
            state_txt = "Session ended"
            if not self._closing:
                self._closing = True
                self.root.after(3000, self.root.destroy)
        el = int(st.get("elapsed_seconds", 0))
        mm, ss = divmod(el, 60)
        self.lbl_status.config(
            text=("%s | %02d:%02d | Order %d" % (state_txt, mm, ss, st["order_count"])
                  + (("  |  " + " ".join(st["active_mods"])) if st.get("active_mods") else "")),
            fg=RED if any(k in state_txt for k in ("Critical", "Tampered", "Rollback", "Unnamed", "Margin call", "Negative equity")) else MUTED)

        # Positions table
        for row in self.tree.get_children():
            self.tree.delete(row)
        if not st["positions"]:
            # When flat, keep trades from the last 2 minutes here so the table is not empty right after an action
            now = time.time()
            recent = [e for e in st.get("events", [])
                      if e["kind"] in ("open", "close")
                      and now - float(e.get("time", 0)) < 120][-3:]
            if recent:
                self.tree.insert("", "end", values=(
                    "(Flat) · last %d" % len(recent), "", "", "", "", "", "", ""))
                for e in reversed(recent):
                    self.tree.insert("", "end", values=(
                        "  [t%d] %s" % (e["tick"], e["text"][:26]), "", "", "", "", "", "", ""))
            else:
                self.tree.insert("", "end", values=("(Flat)", "", "", "", "", "", "", ""))
        else:
            for p in st["positions"]:
                self.tree.insert("", "end", values=(
                    p["pair"], "Long" if p["side"] == "LONG" else "Short",
                    "%.0f" % p["lots"], "%dx" % p["leverage"],
                    "%.4f" % p["entry"], "%.4f" % p["price"],
                    "%.0f" % p["margin"], "%+.0f" % p["upnl"]))

        # Quote board
        hist = st.get("price_history", {})
        for sym, q in st["prices"].items():
            pair = self.price_labels.get(sym)
            if not pair:
                continue
            name_lbl, val_lbl = pair
            h = hist.get(sym) or []
            base = h[0] if h else q["price"]
            chg = (q["price"] / base - 1) * 100 if base else 0
            arrow = "▲" if chg > 0.0005 else ("▼" if chg < -0.0005 else "·")
            color = GREEN if chg > 0.0005 else (RED if chg < -0.0005 else MUTED)
            name_lbl.config(text="%s  %s" % (sym, q["name"]), fg=TEXT)
            val_lbl.config(text="%.4f  %s %+.2f%%" % (q["price"], arrow, chg), fg=color)

        # Curve
        self.curve = st["equity_curve"]
        self._draw_equity()

        # Activity feed (append only on new events; preserve scroll position)
        self._append_log(st.get("events", []))

        # Negative balance: pop the loan self-rescue window once

    def _append_log(self, events):
        if self.log_text is None:
            return
        if not events:
            if self._log_events:
                self._log_events = []
                self._render_log()
            return
        fresh = []
        for e in events:
            key = (e.get("tick"), e.get("text"))
            if key in self._log_seen:
                continue
            self._log_seen.add(key)
            fresh.append(e)
        if len(self._log_seen) > 400:
            self._log_seen.clear()
            for e in events:
                self._log_seen.add((e.get("tick"), e.get("text")))
        if not fresh:
            return
        self._log_events.extend(fresh)
        if len(self._log_events) > 300:
            self._log_events = self._log_events[-300:]
        self._write_log(fresh)

    def _log_cat(self, e):
        """Bucket one event into a quick-filter tab."""
        k = e.get("kind", "info")
        t = e.get("text", "")
        if k == "gap":
            return "liq" if any(m in t for m in _LIQ_MARKS) else "gap"
        if k == "news":
            return "news"
        if k in ("open", "close"):
            return "trade"
        if k in ("stopout", "blowup", "margin_call", "warn"):
            return "risk"
        return "other"

    def _set_log_filter(self, key):
        if key == self._log_filter:
            return
        self._log_filter = key
        self._paint_log_tabs()
        self._render_log()

    def _paint_log_tabs(self):
        for key, btn in self._log_tabs.items():
            on = (key == self._log_filter)
            btn.config(bg=BLUE if on else "#F1F1F1",
                       fg="#FFFFFF" if on else MUTED,
                       activebackground=BLUE if on else "#E5E5E5",
                       activeforeground="#FFFFFF" if on else MUTED)

    def _render_log(self):
        if self.log_text is None:
            return
        rows = self._log_events if self._log_filter == "all" else [
            e for e in self._log_events if self._log_cat(e) == self._log_filter]
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self._write_rows(rows)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _write_log(self, fresh):
        rows = fresh if self._log_filter == "all" else [
            e for e in fresh if self._log_cat(e) == self._log_filter]
        if not rows:
            return
        at_bottom = self.log_text.yview()[1] >= 0.999
        top = self.log_text.yview()[0]
        self.log_text.config(state="normal")
        self._write_rows(rows)
        if at_bottom:
            self.log_text.see("end")
        else:
            self.log_text.yview_moveto(top)
        self.log_text.config(state="disabled")

    def _write_rows(self, rows):
        # Color by event kind: danger -> red/orange, opportunity -> blue, fill -> green, cash -> purple, ambiance -> gray
        kind_color = {
            "blowup": "#8B0000",      # blown out: dark red
            "stopout": RED,           # forced liquidation: red
            "gap": "#E07000",         # Black Swan gap: orange-red
            "news": PURPLE,           # breaking news: purple
            "warn": ORANGE,           # warning (negative cash, abnormal exit): orange
            "margin_call": YELLOW,    # margin call: dark gold
            "open": BLUE,             # position opened: blue
            "close": GREEN,           # position closed: green
            "loan": "#7B2FBE",        # loan: purple
            "end": "#444444",         # match ended: dark grey
            "trader": "#44546A",      # identity: blue-grey
            "info": MUTED,            # ambient: grey
        }
        for e in rows:
            k = e.get("kind", "info")
            self.log_text.insert("end", "[t%d] %s\n" % (e["tick"], e["text"]), k)
            self.log_text.tag_config(k, foreground=kind_color.get(k, MUTED))

    def _draw_equity(self):
        c = self.equity_canvas
        c.delete("all")
        w = max(c.winfo_width(), 100)
        h = max(c.winfo_height(), 100)
        if len(self.curve) < 2:
            c.create_text(w / 2, h / 2, text="No data", fill=MUTED, font=FONT)
            return

        eqs = [p["equity"] for p in self.curve]
        lo, hi = min(eqs), max(eqs)
        span = hi - lo
        if span < 1:
            span = 1.0
        lo -= span * 0.10
        hi += span * 0.10
        pad_l, pad_r, pad_t, pad_b = 72, 18, 16, 26
        n = len(eqs)

        def xy(i, v):
            x = pad_l + (w - pad_l - pad_r) * (i / (n - 1))
            y = h - pad_b - (h - pad_t - pad_b) * ((v - lo) / (hi - lo))
            return (x, y)

        # Horizontal grid + ticks
        for i in range(5):
            v = lo + (hi - lo) * i / 4
            _, gy = xy(0, v)
            c.create_line(pad_l, gy, w - pad_r, gy, fill="#EEEEEE")
            c.create_text(pad_l - 8, gy, text="{:,.0f}".format(v), anchor="e",
                          fill=MUTED, font=FONT_TINY)

        # Starting-capital dashed line
        if lo <= 1_000_000 <= hi:
            _, by = xy(0, 1_000_000)
            c.create_line(pad_l, by, w - pad_r, by, fill="#B9B9B9", dash=(4, 4))
            c.create_text(w - pad_r, by - 9, text="Initial 1,000,000", fill="#9A9A9A",
                          anchor="e", font=FONT_TINY)

        pts = [xy(i, v) for i, v in enumerate(eqs)]
        color = GREEN if eqs[-1] >= eqs[0] else RED

        # Area fill (stipple fakes transparency)
        poly = [pts[0][0], h - pad_b] + [v for p in pts for v in p] + [pts[-1][0], h - pad_b]
        c.create_polygon(*poly, fill=color, stipple="gray12", outline="")

        # Main polyline: green/red above 0, turns purple over the whole stretch once it drops below 0 (debt)
        for i in range(n - 1):
            seg = PURPLE if min(eqs[i], eqs[i + 1]) < 0 else color
            c.create_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                          fill=seg, width=2)

        # Zero axis (draw a purple line where net value crosses 0 so the "debt zone" has a clear boundary)
        if lo < 0 < hi:
            _, zy = xy(0, 0)
            c.create_line(pad_l, zy, w - pad_r, zy, fill=PURPLE, dash=(3, 3))
            c.create_text(pad_l - 8, zy, text="0", anchor="e", fill=PURPLE, font=FONT_TINY)

        # Peak / trough
        imax = max(range(n), key=lambda i: eqs[i])
        imin = min(range(n), key=lambda i: eqs[i])
        if imax != imin:
            for i, txt, col, anchor in ((imax, "Peak {:,.0f}".format(eqs[imax]), GREEN, "s"),
                                        (imin, "Trough {:,.0f}".format(eqs[imin]), RED, "n")):
                px, py = xy(i, eqs[i])
                if eqs[i] < 0:
                    col = PURPLE
                c.create_oval(px - 3, py - 3, px + 3, py + 3, fill=col, outline="")
                c.create_text(px, py - 12 if anchor == "s" else py + 12, text=txt,
                              fill=col, anchor=anchor, font=FONT_TINY)

        # Current value
        c.create_text(pad_l + 4, pad_t + 2, text="Current {:,.0f}".format(eqs[-1]),
                      fill=PURPLE if eqs[-1] < 0 else color, font=FONT_MID, anchor="nw")

    # ------------------------------------------------------------ game rules
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

    def _kill_all(self):
        if not messagebox.askyesno("End processes", "The Tokens service will stop immediately and the spectator will close.\nAre you sure?"):
            return
        try:
            post("/shutdown")
        except Exception:
            pass
        self.lbl_status.config(text="Ending processes...", fg=RED)
        self.root.after(700, self.root.destroy)
        self.root.after(1000, lambda: os._exit(0))

    def run(self):
        self.root.mainloop()


def _acquire_single_instance():
    """Only one spectator is allowed per game directory.

    Uses a held local port as a process-level mutex: a successful bind acquires the lock, and the
    OS releases it automatically when the process exits (including a hard kill), so no lock file is
    left behind for manual cleanup.
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
        messagebox.showwarning("Tokens Trading Market", "Spectator opened!")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def main():
    if not _acquire_single_instance():
        _warn_already_open()
        return
    size = (1920, 1080)   # AI edition uses a fixed 1920 layout
    if not size:
        return
    Watch(size).run()


if __name__ == "__main__":
    main()
