using System.Globalization;
using System.Media;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using TokensWatch.Controls;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Panels;
using TokensWatch.Services;

namespace TokensWatch;

public partial class MainWindow : Window
{
    // 系统强调色会把标题栏刷成红色（本机就是这个情况），
    // 和整体的浅灰卡片风格打架。Win11 允许直接指定标题栏配色。
    private const int DWMWA_CAPTION_COLOR = 35;
    private const int DWMWA_TEXT_COLOR = 36;

    [System.Runtime.InteropServices.DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    // ---- 移除标题栏右上角的三个系统按钮 ----
    // 对齐 Python 的 _hide_close_button（第 83-103 行）。理由：看盘时手滑点到 X 窗口就没了，
    // 这一局就再没人盯着；最小化仍可以用顶栏那个自带按钮。
    private const int GWL_STYLE = -16;
    private const int WS_SYSMENU = 0x00080000;
    private const uint SWP_NOSIZE = 0x0001;
    private const uint SWP_NOMOVE = 0x0002;
    private const uint SWP_NOZORDER = 0x0004;
    private const uint SWP_FRAMECHANGED = 0x0020;

    [System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true)]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true)]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);

    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);

        IntPtr hwnd;
        try
        {
            hwnd = new System.Windows.Interop.WindowInteropHelper(this).Handle;
        }
        catch
        {
            return;
        }

        // 1) 标题栏配色跟随浅灰主题，而不是系统强调色（本机是红色）
        try
        {
            int caption = 0x00F3F3F3;   // COLORREF 是 0x00BBGGRR，不是 RGB
            DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ref caption, sizeof(int));
            int text = 0x001A1A1A;
            DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ref text, sizeof(int));
        }
        catch
        {
            // Win10 没有这两个属性，保留系统默认
        }

        // 2) 去掉 最小化 / 最大化 / 关闭
        try
        {
            int style = GetWindowLong(hwnd, GWL_STYLE);
            if ((style & WS_SYSMENU) != 0)
            {
                SetWindowLong(hwnd, GWL_STYLE, style & ~WS_SYSMENU);
                SetWindowPos(hwnd, IntPtr.Zero, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED);
            }
        }
        catch
        {
            // 失败时保留系统按钮，不影响其他功能
        }
    }

    private readonly StateClient _client = new();

    // 主循环 300ms，对齐 Python 侧 self.root.after(delay, self.refresh)
    private readonly DispatcherTimer _uiTimer;
    private const int PollMs = 300;

    // 「外部的怜悯」低频轮询，对齐 _poll_assist
    private readonly DispatcherTimer _assistTimer;
    private const int AssistPollMs = 3000;

    private WatchState? _state;

    private readonly List<GameEvent> _logEvents = new();
    private readonly HashSet<(int Tick, string Text)> _logSeen = new();
    private readonly HashSet<string> _assistSeen = new();

    /// <summary>活动流筛选。主窗口与「活动流（全部）」弹窗共享这一个状态，
    /// 对齐 Python 的 self._log_filter：弹窗里切分类，外面的最新一条也跟着变。</summary>
    private string _logFilter = "all";

    public string LogFilter => _logFilter;

    private readonly Dictionary<string, Sparkline> _sparklines = new();
    private readonly Dictionary<string, TextBlock> _priceTexts = new();
    private readonly Dictionary<string, TextBlock> _chgTexts = new();

    private AssistWindow? _assistWindow;
    private TradeWindow? _tradeWindow;
    private SlotWindow? _slotWindow;
    private LoanRescueWindow? _loanWindow;
    private RulesWindow? _rulesWindow;
    private ScratchWindow? _scratchWindow;
    private LogWindow? _logWindow;
    private HoldWindow? _holdWindow;

    private bool _closing;
    private bool _busy;

    // ---------- Huge Wave warning ----------
    // The engine raises huge_wave.show for the warning tick only and drops it on the next
    // one. Keying on the tick number prevents two things:
    //   1) the same warning being read on two consecutive polls (which would replay the
    //      sound) when polling is slower than the tick clock;
    //   2) a replay after the window is minimised and restored and the UI is rebuilt.
        private bool _hugeWaveShowLatch;   // 上一次渲染时 show 的值，用于取上升沿

    // 出场动画的两个时长（毫秒），只在这里改。
    // 参考：PvZ 原版文字缩放到位实测是 200ms（60fps 下 12 帧），但那是 800×600 的画面；
    // 放到 1920 宽的观众席上观感偏急，按用户反馈放慢到 620/260。
    private const int HugeWaveScaleMs = 620;
    private const int HugeWaveFadeMs = 260;

    private DispatcherTimer? _hugeWaveTimer;


    public MainWindow()
    {
        InitializeComponent();

        BuildPriceGrid();

        _uiTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(PollMs) };
        _uiTimer.Tick += async (_, _) => await PollAsync();

        _assistTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(AssistPollMs) };
        _assistTimer.Tick += async (_, _) => await PollAssistAsync();

        Loaded += (_, _) =>
        {
            // 设计基准是 1920×1080。本机是 2K 屏，正常情况下放得下；
            // 但如果系统缩放调到 150%，1920 DIP 会超出 2560 物理像素宽，
            // 这里兜一层，保证窗口永远不跑到屏幕外。
            var wa = SystemParameters.WorkArea;
            if (Width > wa.Width) Width = wa.Width;
            if (Height > wa.Height) Height = wa.Height;
            Left = wa.Left + (wa.Width - Width) / 2;
            Top = wa.Top + (wa.Height - Height) / 2;

            _uiTimer.Start();
            _assistTimer.Start();
            _ = RunStartupFlowAsync();
        };

        Closed += (_, _) =>
        {
            _uiTimer.Stop();
            _assistTimer.Stop();
            _client.Dispose();
        };
    }

    /// <summary>
    /// 开局流程：难度盲盒 → 规则窗 → begin。
    /// 只在「本局还没定档」时走一遍；已经定档（例如中途重开窗口）就直接进主界面，
    /// 否则每次刷新都要玩家再看一次 30 秒转盘。
    /// </summary>
    private async Task RunStartupFlowAsync()
    {
        try
        {
            var st = await _client.GetStateAsync();
            if (st is null || st.Rolled) return;
            // 新局先问要不要开挑战任务：答复后才起盲盒，询问期间引擎不计时
            if (st.Challenge?.Stage == "ask") return;
            await StartRollFlowAsync();
        }
        catch
        {
            // 盲盒打不开也不能把主界面拖死：下面照常轮询，玩家仍可用「查看规则」
        }
    }

    // ==================== 轮询 ====================

    private async Task PollAsync()
    {
        if (_busy || _closing) return;
        _busy = true;
        try
        {
            var st = await _client.GetStateAsync();
            if (st is null) return;
            _state = st;
            Render(st);
        }
        catch (Exception ex)
        {
            // 服务未启动 / 中途重启 / 反序列化失败都会到这里。
            // 必须把原因显示出来，否则界面只会停在「等待服务启动」，排查时两眼一抹黑。
            if (_state is null)
            {
                string msg = ex.Message.Replace("\r", " ").Replace("\n", " ");
                if (msg.Length > 80) msg = msg[..80] + "…";
                TxtRunState.Text = "连接失败：" + msg;
                TxtRunState.Foreground = Theme.Red;
            }
        }
        finally
        {
            _busy = false;
        }
    }

    private Task PollAssistAsync()
    {
        // 人类版没有「外部的怜悯」通道——那是 AI 版专有的求助机制。
        // 保留空实现，避免主循环里还要分叉判断。
        return Task.CompletedTask;
    }

    // ==================== 渲染 ====================

    private void Render(WatchState st)
    {
        // ---------- Huge Wave warning (PvZ port) ----------
        // First, because it is a full-screen event: nothing else may outrank it.
        RenderHugeWave(st);

        // ---------- 挑战任务（PvZ2 Level Objectives 移植）----------
        RenderChallenge(st);

        // ---------- 顶栏 ----------
        TxtTrader.Text = string.IsNullOrEmpty(st.Trader) ? "访客" : st.Trader;
        TxtMode.Text = st.EventsOn ? "已开启随机事件" : "理想情况";
        TxtMode.Foreground = st.EventsOn ? Theme.Blue : Theme.Muted;

        // 全局事件各自一个胶囊：开哪个显示哪个，不拼成一条。
        bool fr = st.Special?.Fr == true;
        bool slot = st.Special?.Slot == true;
        ChipFr.Visibility = fr ? Visibility.Visible : Visibility.Collapsed;
        ChipSlot.Visibility = slot ? Visibility.Visible : Visibility.Collapsed;
        ChipSpecial.Visibility = (fr || slot) ? Visibility.Collapsed : Visibility.Visible;

        // ---------- 指标卡 ----------
        TxtEquity.Text = st.Equity.ToString("N0", CultureInfo.CurrentCulture);
        TxtEquity.Foreground = st.Equity >= 1_000_000 ? Theme.Green : Theme.Red;

        TxtPnl.Text = $"{st.Pnl:+#,0;-#,0;0} ({st.PnlPct:+0.00;-0.00;0.00}%)";
        TxtPnl.Foreground = st.Pnl >= 0 ? Theme.Green : Theme.Red;

        if (st.MarginLevel is { } ml)
        {
            TxtMargin.Text = ml.ToString("0.0", CultureInfo.CurrentCulture) + "%";
            TxtMargin.Foreground = ml < 50 ? Theme.Red : ml < 150 ? Theme.Orange : Theme.Ink;
        }
        else
        {
            TxtMargin.Text = "—";
            TxtMargin.Foreground = Theme.Muted;
        }

        TxtTargetPct.Text = st.TargetPct.ToString("0.0", CultureInfo.CurrentCulture) + "%";
        TxtTargetPct.Foreground = st.TargetPct >= 100 ? Theme.Green : Theme.Blue;

        // ---------- 资金行 ----------
        var loan = st.Loan;
        string rateTxt = loan is null ? "—" : $"{loan.RatePct:0.000}%/tick";
        TxtFunds.Text = loan is null
            ? $"可贷 — | 现金 {st.Balance:N0}"
            : $"可贷 {loan.Limit:N0} | 现金 {st.Balance:N0} | 已借 {st.TotalBorrowed:N0} | " +
              $"欠款 {loan.Balance:N0} | 利息 {loan.Interest:N0} | {rateTxt}";
        TxtFunds.Foreground = st.TotalBorrowed > 0 ? Theme.Red : Theme.Blue;

        // ---------- 运行状态文案 ----------
        string stateTxt = "正常交易中";
        if (st.NegativeRemain is { } nr)
            stateTxt = $"资金为负·还剩 {(int)nr} 秒借款，否则结束";
        else if (st.Tampered)
            stateTxt = "存档被篡改·已重置";
        else if (st.ClockCheat)
            stateTxt = "时钟被回拨·计时已冻结";
        else if (st.MarginCallRemain is { } mcr)
            stateTxt = $"追加保证金·还剩 {(int)mcr} tick";
        else if (st.Unnamed)
            stateTxt = "未命名启动·请用开一局.bat";
        else if (st.MarginLevel is { } mlv && mlv < 50)
            stateTxt = "保证金水平告急";
        else if (st.Blowups > 0 && st.MarginLevel is null)
            stateTxt = $"已爆仓 {st.Blowups} 次";

        if (st.Finished) stateTxt = "本局已结束";

        int elapsed = (int)Math.Max(0, st.ElapsedSeconds);
        int mm = elapsed / 60, ss = elapsed % 60;

        string mods = st.ActiveModsText();
        TxtRunState.Text = $"{stateTxt} | {mm:00}:{ss:00} | 订单 {st.OrderCount}" +
                           (mods.Length > 0 ? "  |  " + mods : "");

        bool danger = new[] { "告急", "篡改", "回拨", "未命名", "追加保证金", "资金为负" }
            .Any(k => stateTxt.Contains(k));
        TxtRunState.Foreground = danger ? Theme.Red : Theme.Muted;

        // ---------- 统计行 ----------
        string mddTxt = st.MaxDrawdown is { } mdd ? $"{mdd:0.00}%" : "—";
        string shp = st.Sharpe is { } s ? s.ToString("0.00", CultureInfo.CurrentCulture) : "—";
        string winRate = st.ClosedN > 0
            ? (st.WinN * 100.0 / st.ClosedN).ToString("0.0", CultureInfo.CurrentCulture) + "%"
            : "—";
        double fee = st.Fees + st.Swap;

        TxtStats.Text = $"目标 {st.Target:N0}" +
                        (st.TargetBonus > 0 ? $"（贷款上浮 +{st.TargetBonus:N0}）" : "") +
                        $" | 回撤 {mddTxt} | 夏普 {shp} | {st.ClosedN} 笔 · 胜率 {winRate} | 费息 {fee:N0}";

        // ---------- 快进 ----------
        if (st.Ff is { } ff)
        {
            double usedSum = ff.Records.Sum();
            string txt = "快进剩 " + FmtFf(ff.Remain);
            if (ff.Records.Count > 0) txt += " | 已用 " + FmtFf(usedSum);
            if (ff.CoolLeft > 0) txt += $" | 冷却 {(int)Math.Ceiling(ff.CoolLeft)} 秒";
            TxtFastForward.Text = txt;
            TxtFastForward.Foreground = ff.CoolLeft > 0 ? Theme.Red : Theme.Muted;
        }

        // ---------- 时间进度 ----------
        double total = Math.Max(1, st.SessionMinutes * 60.0);
        double frac = Math.Clamp(st.ElapsedSeconds / total, 0, 1);
        double remain = Math.Max(0, total - st.ElapsedSeconds);
        if (BarTime.Parent is FrameworkElement track && track.ActualWidth > 0)
            BarTime.Width = Math.Max(0, track.ActualWidth * frac);
        BarTime.Background = frac < 0.8 ? Theme.Blue : Theme.Orange;
        TxtTimeLeft.Text = $"剩余 {(int)remain / 60:00}:{(int)remain % 60:00}";
        TxtTimeLeft.Foreground = frac < 0.8 ? Theme.Muted : Theme.Orange;

        // ---------- 运行状态面板 ----------
        TxtAudit.Text = st.Audit.Count > 0 ? $"{st.Audit.Count} 项告警" : "通过（4 条恒等式）";
        TxtAudit.Foreground = st.Audit.Count > 0 ? Theme.Red : Theme.Green;

        string gapPct = st.GapLevel is not null && Theme.GapPct.TryGetValue(st.GapLevel, out var gp) ? gp : "?";
        TxtGap.Text = $"{st.GapLevel ?? "—"}（{gapPct}/tick）";

        string liqPct = st.LiqLevel is not null && Theme.LiqPct.TryGetValue(st.LiqLevel, out var lp) ? lp : "?";
        TxtLiq.Text = $"{st.LiqLevel ?? "—"}（{liqPct} 往返）";

        TxtFf.Text = st.Ff is null ? "—" : FmtFf(st.Ff.Remain);
        var specialNames = new List<string>();
        if (fr) specialNames.Add(Theme.FrName);
        if (slot) specialNames.Add(Theme.SlotName);
        TxtSpecialState.Text = specialNames.Count > 0 ? string.Join("、", specialNames) : "无";

        // 峰值 / 谷值：直接取曲线上的极值，和图上标注的是同一组数字。
        // 只有 1 个点时（刚开局）没有“波动”可言，峰谷会等于本金，显示出来
        // 反而让人以为「全程零波动」，与图表显示的「暂无数据」也对不上，
        // 所以阈值统一用 2，和数据曲线保持一致。
        if (st.EquityCurve.Count >= 2)
        {
            double peak = double.MinValue, trough = double.MaxValue;
            foreach (var p in st.EquityCurve)
            {
                if (p.Equity > peak) peak = p.Equity;
                if (p.Equity < trough) trough = p.Equity;
            }

            TxtPeak.Text = peak.ToString("N0", CultureInfo.CurrentCulture);
            TxtPeak.Foreground = peak >= 1_000_000 ? Theme.Green : Theme.Red;

            TxtTrough.Text = trough.ToString("N0", CultureInfo.CurrentCulture);
            TxtTrough.Foreground = trough >= 1_000_000 ? Theme.Green : Theme.Red;
        }
        else
        {
            TxtPeak.Text = "—";
            TxtTrough.Text = "—";
            TxtPeak.Foreground = Theme.Muted;
            TxtTrough.Foreground = Theme.Muted;
        }

        TxtRisk.Text = $"回撤 {mddTxt} · 夏普 {shp}";

        var hwi = st.HugeWave;
        TxtHugeWave.Text = hwi is null
            ? "—"
            : string.Format("共 {0} 次 | 已触发 {1} | 未触发 {2}", hwi.Total, hwi.Fired, hwi.Left);

        // ---------- 曲线 ----------
        ChartEquity.SetData(st.EquityCurve, baseLine: 1_000_000, target: st.Target);

        // ---------- 持仓 ----------
        RenderPositions(st);

        // ---------- 报价台 ----------
        RenderPrices(st);

        // ---------- 活动流 ----------
        AppendEvents(st);

        // ---------- 附属窗口跟随主循环 ----------
        RefreshHoldPanel();
        _tradeWindow?.UpdateState(st);

        // ---------- 负资产：强制进入贷款自救 ----------
        if (st.NegativeRemain is not null)
        {
            if (_loanWindow is not { IsLoaded: true })
            {
                _loanWindow = new LoanRescueWindow(_client, st) { Owner = this };
                _loanWindow.Closed += (_, _) => _loanWindow = null;
                _loanWindow.Show();
            }
            else
            {
                _loanWindow.UpdateState(st);
            }
        }
        else if (_loanWindow is { IsLoaded: true })
        {
            _loanWindow.ForceClose();
        }
    }

    private void RenderPositions(WatchState st)
    {
        HoldRows.Children.Clear();

        if (st.Positions.Count == 0)
        {
            // 空态塌缩：不画表头，只留一句提示，避免 260px 的空白
            HoldHeader.Visibility = Visibility.Collapsed;
            TxtHoldEmpty.Visibility = Visibility.Visible;
            BtnHoldMore.Visibility = Visibility.Collapsed;
            return;
        }

        HoldHeader.Visibility = Visibility.Visible;
        TxtHoldEmpty.Visibility = Visibility.Collapsed;
        BtnHoldMore.Visibility = st.Positions.Count > 7 ? Visibility.Visible : Visibility.Collapsed;

        foreach (var p in st.Positions.Take(7))
        {
            var row = new UniformGrid { Columns = 8, Margin = new Thickness(0, 3, 0, 3) };

            row.Children.Add(Cell(p.Pair, Theme.Brush(Theme.PairColor(p.Pair)), left: true));
            row.Children.Add(Cell(p.Side == "LONG" ? "多" : "空",
                                  p.Side == "LONG" ? Theme.Green : Theme.Red));
            row.Children.Add(Cell(p.Lots.ToString("0.##", CultureInfo.CurrentCulture)));
            row.Children.Add(Cell(p.Leverage.ToString("0", CultureInfo.CurrentCulture) + "x"));
            row.Children.Add(Cell(p.Entry.ToString("0.##", CultureInfo.CurrentCulture), mono: true));
            row.Children.Add(Cell(p.Price.ToString("0.##", CultureInfo.CurrentCulture), mono: true));
            row.Children.Add(Cell(p.Margin.ToString("N0", CultureInfo.CurrentCulture), mono: true));
            row.Children.Add(Cell(p.Upnl.ToString("+#,0;-#,0;0", CultureInfo.CurrentCulture),
                                  p.Upnl >= 0 ? Theme.Green : Theme.Red, mono: true));

            HoldRows.Children.Add(row);
        }
    }

    private static TextBlock Cell(string text, Brush? brush = null, bool mono = false, bool left = false)
    {
        var tb = new TextBlock
        {
            Text = text,
            FontSize = 13,
            FontFamily = new FontFamily(mono ? Theme.MonoFont : Theme.UiFont),
            HorizontalAlignment = left ? HorizontalAlignment.Left : HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = brush ?? Theme.Ink,
            TextTrimming = TextTrimming.CharacterEllipsis,
        };
        if (left) tb.Margin = new Thickness(4, 0, 0, 0);
        return tb;
    }

    private void BuildPriceGrid()
    {
        PriceGrid.Children.Clear();
        _sparklines.Clear();
        _priceTexts.Clear();
        _chgTexts.Clear();

        foreach (var pair in Theme.PairOrder)
        {
            var colorHex = Theme.PairColor(pair);
            var colorBrush = Theme.Brush(colorHex);

            var name = new TextBlock
            {
                Text = pair,
                FontSize = 11,
                FontFamily = new FontFamily(Theme.MonoFont),
                Foreground = Theme.Muted,
                VerticalAlignment = VerticalAlignment.Center,
            };

            var price = new TextBlock
            {
                Text = "—",
                FontSize = 15,
                FontWeight = FontWeights.Bold,
                FontFamily = new FontFamily(Theme.UiFont),
                Foreground = Theme.Ink,
                Margin = new Thickness(8, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
            };

            var chg = new TextBlock
            {
                Text = "",
                FontSize = 11,
                FontFamily = new FontFamily(Theme.MonoFont),
                Foreground = Theme.Muted,
                Margin = new Thickness(8, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
            };

            // 7 列时每格只有约 200px：品种名、价格、涨跌挤在一行会被裁掉，
            // 所以拆成「名称 + 涨跌」一行、「价格」一行的两行结构。
            chg.Margin = new Thickness(0);
            chg.HorizontalAlignment = HorizontalAlignment.Right;

            var topLine = new Grid();
            topLine.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            topLine.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            Grid.SetColumn(name, 0);
            Grid.SetColumn(chg, 1);
            topLine.Children.Add(name);
            topLine.Children.Add(chg);

            price.Margin = new Thickness(0, 3, 0, 0);

            var spark = new Sparkline { Height = 48, Margin = new Thickness(0, 6, 0, 0) };

            var body = new StackPanel();
            body.Children.Add(topLine);
            body.Children.Add(price);
            body.Children.Add(spark);

            var bar = new Border
            {
                Width = 3,
                Background = colorBrush,
                CornerRadius = new CornerRadius(1.5),
                Margin = new Thickness(0, 0, 8, 0),
            };

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            Grid.SetColumn(bar, 0);
            Grid.SetColumn(body, 1);
            grid.Children.Add(bar);
            grid.Children.Add(body);

            var card = new Border
            {
                Padding = new Thickness(10, 8, 10, 8),
                Margin = new Thickness(4),
                CornerRadius = new CornerRadius(6),
                Background = Theme.Brush("#FAFAFA"),
                Child = grid,
            };

            PriceGrid.Children.Add(card);

            _sparklines[pair] = spark;
            _priceTexts[pair] = price;
            _chgTexts[pair] = chg;
        }
    }

    private void RenderPrices(WatchState st)
    {
        foreach (var pair in Theme.PairOrder)
        {
            if (!st.Prices.TryGetValue(pair, out var q)) continue;

            if (_priceTexts.TryGetValue(pair, out var pt))
                pt.Text = q.Price.ToString("0.0000", CultureInfo.CurrentCulture);

            List<double>? hist = null;
            if (st.PriceHistory is not null && st.PriceHistory.TryGetValue(pair, out var h))
                hist = h;

            if (hist is { Count: >= 2 } && _chgTexts.TryGetValue(pair, out var ct))
            {
                double first = hist[0];
                double last = hist[^1];
                double pct = first > 1e-9 ? (last - first) / first * 100.0 : 0.0;
                ct.Text = $"{pct:+0.00;-0.00;0.00}%";
                ct.Foreground = pct >= 0 ? Theme.Green : Theme.Red;
            }

            if (_sparklines.TryGetValue(pair, out var sp))
                sp.SetData(hist, Theme.PairColor(pair));
        }
    }

    private void AppendEvents(WatchState st)
    {
        bool added = false;
        foreach (var e in st.Events)
        {
            var key = (e.Tick, e.Text ?? "");
            if (!_logSeen.Add(key)) continue;
            _logEvents.Add(e);
            added = true;
        }

        if (!added) return;

        if (_logEvents.Count > 300)
            _logEvents.RemoveRange(0, _logEvents.Count - 300);

        RenderLogFeed();
        _logWindow?.AppendAll(_logEvents);
    }

    /// <summary>
    /// 右栏活动流：最新在上，最多渲染 30 条，超出靠滚动。
    /// 原版主窗口只显示最新 1 条，等于把一整个区块让给一行字——这里把空间用满。
    /// </summary>
    /// <summary>由「活动流（全部）」弹窗回调，保证内外两处筛选一致。</summary>
    public void SetLogFilter(string key)
    {
        if (_logFilter == key) return;
        _logFilter = key;
        RenderLogFeed();
    }

    /// <summary>
    /// Render entry for the Huge Wave warning.
    /// _roll_huge_wave() in the engine is a three-stage set piece: the warning tick flips
    /// show to true -> a silent two-tick hold -> an all-at-once burst. This handles stage
    /// one only (banner + sound); the burst is ordinary event flow shown in the activity feed.
    /// </summary>
    private void RenderHugeWave(WatchState st)
    {
        var hw = st.HugeWave;
        if (hw is null) return;          // older engine without the field: treat as no warning

        // Only act on the tick that should raise the banner. Dismissal is owned by the
        // 10 s timer started in ShowHugeWave, not by show flipping back -- otherwise the
        // next tick (5 s later) would cut the set piece in half while the sound is still playing.
        // Play on the RISING EDGE of show only. The engine nominally raises show for a
        // single tick, but a data source that keeps show=true across two consecutive
        // ticks made the old per-tick de-duplication play the banner twice (observed on
        // real data). A boolean latch is independent of tick numbering and cannot misfire.
        bool rising = hw.Show && !_hugeWaveShowLatch;
        _hugeWaveShowLatch = hw.Show;
        if (!rising) return;

        ShowHugeWave(string.IsNullOrWhiteSpace(hw.Text)
            ? "A HUGE WAVE OF VOLATILITY IS APPROACHING!" : hw.Text);
    }


    /// <summary>
    /// 挑战任务卡片。四种 stage：
    ///   none —— 还没定档，按「未开启」显示；
    ///   ask  —— 定档后等参赛者决定，三条候选已经列出并带倒计时；
    ///   on   —— 已开启，逐条显示 √ / × / ·；
    ///   off  —— 参赛者选择不开启。
    /// 判定与破功由引擎负责，这里只负责把状态画出来，不参与任何计算。
    /// </summary>
    private void RenderChallenge(WatchState st)
    {
        var ch = st.Challenge;
        ChallengeList.Children.Clear();

        string stage = ch?.Stage ?? "none";
        if (ch is null || (stage != "ask" && stage != "on"))
        {
            TxtChallengeHint.Text = "本局游戏参赛者未开启挑战任务";
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "";
            ChallengeActions.Visibility = Visibility.Collapsed;
            return;
        }

        foreach (var t in ch.Tasks)
            ChallengeList.Children.Add(BuildChallengeRow(t));

        if (stage == "ask")
        {
            TxtChallengeHint.Text = string.Format(
                "等待参赛者决定是否开启…（还剩 {0:0} 秒，超时按不开启处理）；开启后将在难度定档时公布三条目标", ch.AskLeft);
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "待确认";
            ChallengeActions.Visibility = Visibility.Visible;
        }
        else if (ch.Tasks.Count == 0)
        {
            TxtChallengeHint.Text = "已开启，抽完难度后公布三条目标";
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "待定档";
        }
        else
        {
            TxtChallengeHint.Visibility = Visibility.Collapsed;
            TxtChallengeCount.Text = string.Format("{0}/{1} 已达成", ch.Cleared, ch.Total);
            ChallengeActions.Visibility = Visibility.Collapsed;
        }
    }

    private async void OnChallengeAcceptClick(object sender, RoutedEventArgs e)
    {
        ChallengeActions.Visibility = Visibility.Collapsed;
        await _client.ChallengeAcceptAsync();
        await StartRollFlowAsync();
    }

    private async void OnChallengeDeclineClick(object sender, RoutedEventArgs e)
    {
        ChallengeActions.Visibility = Visibility.Collapsed;
        await _client.ChallengeDeclineAsync();
        await StartRollFlowAsync();
    }

    /// <summary>
    /// 挑战任务答复之后才起难度盲盒 → 规则窗 → begin。
    /// 询问期间引擎刻意不跑盲盒倒计时，所以这一段必须等玩家先做选择。
    /// </summary>
    private async Task StartRollFlowAsync()
    {
        try
        {
            var st = await _client.GetStateAsync();
            if (st is null || st.Rolled) return;
            if (st.Paused) await _client.RollStartAsync();
            var roll = new RollWindow(_client, thenRules: true) { Owner = this };
            roll.ShowDialog();
        }
        catch (Exception ex)
        {
            // 盲盒打不开也不能拖死主界面
            System.Diagnostics.Debug.WriteLine("start roll flow: " + ex.Message);
        }
    }

    private static Brush BrushOf(string hex) =>
        new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));

    private UIElement BuildChallengeRow(ChallengeTask t)
    {
        var grid = new Grid { Margin = new Thickness(0, 0, 0, 9) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        string mark, hex;
        switch (t.Status)
        {
            case "done": mark = "√"; hex = Theme.GreenHex; break;
            case "failed": mark = "×"; hex = Theme.RedHex; break;
            default: mark = "·"; hex = Theme.MutedHex; break;
        }

        var tick = new TextBlock
        {
            Text = mark,
            FontFamily = new FontFamily(Theme.UiFont),
            FontSize = 17,
            FontWeight = FontWeights.Bold,
            Foreground = BrushOf(hex),
            Margin = new Thickness(0, -1, 11, 0),
            VerticalAlignment = VerticalAlignment.Top,
        };
        Grid.SetColumn(tick, 0);
        grid.Children.Add(tick);

        var box = new StackPanel();
        box.Children.Add(new TextBlock
        {
            Text = t.Name,
            FontFamily = new FontFamily(Theme.UiFont),
            FontSize = 14,
            FontWeight = FontWeights.SemiBold,
            Foreground = BrushOf(t.Status == "failed" ? Theme.MutedHex : Theme.TextHex),
            TextWrapping = TextWrapping.Wrap,
        });
        box.Children.Add(new TextBlock
        {
            Text = t.Desc,
            FontFamily = new FontFamily(Theme.UiFont),
            FontSize = 12.5,
            Foreground = BrushOf(Theme.MutedHex),
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 1, 0, 0),
        });
        if (!string.IsNullOrEmpty(t.Note) && t.Status != "pending")
        {
            box.Children.Add(new TextBlock
            {
                Text = t.Note,
                FontFamily = new FontFamily(Theme.UiFont),
                FontSize = 12,
                Foreground = BrushOf(hex),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 1, 0, 0),
            });
        }
        Grid.SetColumn(box, 1);
        grid.Children.Add(box);
        return grid;
    }

    private void ShowHugeWave(string text)
    {
        // Outline layer and body must carry identical text, or the two layers ghost apart.
        HugeWaveText.Text = text;
        HugeWaveOutline.Text = text;
        HugeWaveLayer.Visibility = Visibility.Visible;

        // ---- Entrance: uniform scale-down + fade-in ----
        // Starts at 1.55x and settles at 1.0; durations come from the HugeWaveScaleMs / HugeWaveFadeMs constants.
        // Numbers measured frame by frame from the original footage: appears 34.083s,
        // settles 34.283s (12 frames at 60 fps), peak width ~1.5x, bottom edge y=354 fixed.
        // in about 400 ms. ScaleX and ScaleY move together, so glyphs are never squashed.
        var easeOut = new CubicEase { EasingMode = EasingMode.EaseOut };

        HugeWaveBanner.BeginAnimation(UIElement.OpacityProperty,
            new DoubleAnimation(0.0, 1.0, TimeSpan.FromMilliseconds(HugeWaveFadeMs)) { EasingFunction = easeOut });

        HugeWaveScale.BeginAnimation(ScaleTransform.ScaleXProperty,
            new DoubleAnimation(1.55, 1.0, TimeSpan.FromMilliseconds(HugeWaveScaleMs)) { EasingFunction = easeOut });

        HugeWaveScale.BeginAnimation(ScaleTransform.ScaleYProperty,
            new DoubleAnimation(1.55, 1.0, TimeSpan.FromMilliseconds(HugeWaveScaleMs)) { EasingFunction = easeOut });

        PlayHugeWaveSound();

        // The original clears the banner at mHugeWaveCountDown == 0. Mapped to this engine
        // that is exactly one hold: HUGE_WAVE_WARN_TICKS = 2 ticks = 10 s, which covers
        _hugeWaveTimer?.Stop();
        _hugeWaveTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(10) };
        _hugeWaveTimer.Tick += (_, _) =>
        {
            _hugeWaveTimer?.Stop();
            HideHugeWave();
        };
        _hugeWaveTimer.Start();
    }

    private void HideHugeWave()
    {
        // Exit is animated too: fade out, no hard cut.
        var fade = new DoubleAnimation(1.0, 0.0, TimeSpan.FromMilliseconds(220));
        fade.Completed += (_, _) =>
        {
            HugeWaveLayer.Visibility = Visibility.Collapsed;
            // Reset so the next entrance starts from 1.55x / transparent again; without this
            // the second warning would appear instantly with no animation at all.
            HugeWaveBanner.BeginAnimation(UIElement.OpacityProperty, null);
            HugeWaveBanner.Opacity = 0;
            HugeWaveScale.BeginAnimation(ScaleTransform.ScaleXProperty, null);
            HugeWaveScale.ScaleX = 1.55;
            HugeWaveScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
            HugeWaveScale.ScaleY = 1.55;
        };
        HugeWaveBanner.BeginAnimation(UIElement.OpacityProperty, fade);
    }

    private static void PlayHugeWaveSound()
    {
        try
        {
            SystemSounds.Exclamation.Play();
        }
        catch
        {
            // 音频不可用时仍保留预警横幅。
        }
    }

    private void RenderLogFeed()
    {
        LogFeed.Children.Clear();

        var rows = _logFilter == "all"
            ? _logEvents
            : _logEvents.Where(e => EventKind.Category(e) == _logFilter).ToList();

        for (int i = rows.Count - 1; i >= 0 && LogFeed.Children.Count < 30; i--)
        {
            var e = rows[i];
            LogFeed.Children.Add(new TextBlock
            {
                Text = $"[t{e.Tick}] {e.Text}",
                FontSize = 14,
                FontFamily = new FontFamily(Theme.UiFont),
                Foreground = Theme.Brush(EventKind.ColorHex(e)),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 3, 0, 3),
            });
        }

        if (LogFeed.Children.Count == 0)
        {
            LogFeed.Children.Add(new TextBlock
            {
                Text = "等待事件…",
                FontSize = 13,
                Foreground = Theme.Muted,
            });
        }
    }

    private static string KindColor(string kind, string text)
    {
        // 对齐 Python _write_rows 的 kind_color；黑天鹅里要拆出「流动性枯竭」
        if (kind == "gap")
        {
            bool isLiq = text.Contains("流动性枯竭") || text.Contains("Liquidity drained");
            return isLiq ? Theme.LogLiqHex : Theme.LogGapHex;
        }

        return kind switch
        {
            "news" => Theme.LogNewsHex,
            "open" or "close" => Theme.LogTradeHex,
            "stopout" or "blowup" or "margin_call" or "warn" => Theme.LogRiskHex,
            "loan" => Theme.LogLoanHex,
            "end" => Theme.LogEndHex,
            "trader" => Theme.LogTraderHex,
            _ => Theme.MutedHex,
        };
    }

    private static string FmtFf(double sec)
    {
        int s = (int)Math.Round(Math.Max(0, sec));
        return $"{s / 60} 分 {s % 60:00} 秒";
    }

    // ==================== 顶栏按钮 ====================

    private void OnMinimizeClick(object sender, RoutedEventArgs e)
        => WindowState = WindowState.Minimized;

    private void OnQuitClick(object sender, RoutedEventArgs e)
    {
        var r = MessageBox.Show(
            "这会把本局服务一起结束，对局将记一次异常退出。\n\n确定要结束吗？",
            "结束相关进程",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);

        if (r != MessageBoxResult.Yes) return;

        try
        {
            // 与 Python 侧「结束相关进程」按钮语义一致：先让服务自己收尾
            _ = _client.PostShutdownAsync();
        }
        catch
        {
            // 服务已经不在也没关系
        }

        _closing = true;
        _uiTimer.Stop();
        _assistTimer.Stop();
        Application.Current.Shutdown();
    }

    private void OnOpenAssistClick(object sender, RoutedEventArgs e)
    {
        if (_assistWindow is { IsLoaded: true })
        {
            _assistWindow.Activate();
            return;
        }

        _assistWindow = new AssistWindow(_client) { Owner = this };
        _assistWindow.Closed += (_, _) => _assistWindow = null;
        _assistWindow.Show();
    }

    private void OnOpenScratchClick(object sender, RoutedEventArgs e)
    {
        if (_scratchWindow is { IsLoaded: true })
        {
            _scratchWindow.Activate();
            return;
        }

        _scratchWindow = new ScratchWindow(_client) { Owner = this };
        _scratchWindow.Closed += (_, _) => _scratchWindow = null;
        _scratchWindow.Show();
    }

    private void OnOpenRulesClick(object sender, RoutedEventArgs e)
    {
        if (_rulesWindow is { IsLoaded: true })
        {
            _rulesWindow.Activate();
            return;
        }

        string mode = _state?.EventsOn == true ? "已开启随机事件" : "理想情况";
        _rulesWindow = new RulesWindow(_client, mode) { Owner = this };
        _rulesWindow.Closed += (_, _) => _rulesWindow = null;
        _rulesWindow.Show();
    }

    private void OnOpenSlotClick(object sender, RoutedEventArgs e)
    {
        if (_state is null) return;

        var sp = _state.Special;
        if (sp is not { Slot: true })
        {
            MessageBox.Show(this,
                "本局未开启【老虎机】。\n开新局时在启动窗口里选择开启即可。",
                "老虎机", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        if ((sp.SlotLeft ?? 0) <= 0)
        {
            MessageBox.Show(this,
                "本局老虎机次数已用完。",
                "老虎机", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        if (_slotWindow is { IsLoaded: true })
        {
            _slotWindow.Activate();
            return;
        }

        _slotWindow = new SlotWindow(_client, _state) { Owner = this };
        _slotWindow.Closed += (_, _) => _slotWindow = null;
        _slotWindow.Show();
    }

    private void OnOpenTradeClick(object sender, RoutedEventArgs e)
    {
        if (_tradeWindow is { IsLoaded: true })
        {
            _tradeWindow.Activate();
            return;
        }

        _tradeWindow = new TradeWindow(_client) { Owner = this };
        _tradeWindow.Closed += (_, _) => _tradeWindow = null;
        _tradeWindow.Show();
        if (_state is not null) _tradeWindow.UpdateState(_state);
    }

    private void OnOpenLogClick(object sender, RoutedEventArgs e)
    {
        if (_logWindow is { IsLoaded: true })
        {
            _logWindow.Activate();
            return;
        }

        _logWindow = new LogWindow(this) { Owner = this };
        _logWindow.Closed += (_, _) => _logWindow = null;
        _logWindow.Show();
        _logWindow.AppendAll(_logEvents);
    }

    private void OnOpenHoldClick(object sender, RoutedEventArgs e)
    {
        if (_holdWindow is { IsLoaded: true })
        {
            _holdWindow.Activate();
            return;
        }

        _holdWindow = new HoldWindow { Owner = this };
        _holdWindow.Closed += (_, _) => _holdWindow = null;
        _holdWindow.Show();
        if (_state is not null) _holdWindow.UpdateRows(_state.Positions);
    }

    /// <summary>持仓弹窗需要跟随主循环刷新，由主循环推动。</summary>
    public void RefreshHoldPanel()
    {
        if (_holdWindow is { IsLoaded: true } && _state is not null)
            _holdWindow.UpdateRows(_state.Positions);
    }
}
