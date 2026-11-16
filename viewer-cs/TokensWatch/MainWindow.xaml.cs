using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
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
    private ScratchWindow? _scratchWindow;
    private LogWindow? _logWindow;
    private HoldWindow? _holdWindow;

    private bool _closing;
    private bool _busy;

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
        };

        Closed += (_, _) =>
        {
            _uiTimer.Stop();
            _assistTimer.Stop();
            _client.Dispose();
        };
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

    private async Task PollAssistAsync()
    {
        if (_closing) return;
        try
        {
            var a = await _client.GetAssistPendingAsync();
            if (a is null) return;

            int n = a.Pending.Count;

            var fresh = a.Pending
                .Select(p => p.Ticket)
                .Where(t => !string.IsNullOrEmpty(t) && !_assistSeen.Contains(t))
                .ToList();

            if (fresh.Count > 0)
            {
                foreach (var t in fresh) _assistSeen.Add(t);

                // 对齐 Python 第 584-594 行：新求助到达时响提示音并弹窗。
                // 少了这一步，玩家在别处操作时就会完全错过求助窗口。
                System.Media.SystemSounds.Asterisk.Play();

                string cn = n switch { 1 => "一", 2 => "二", 3 => "三", _ => n.ToString() };
                MessageBox.Show(
                    this,
                    $"您收到{cn}条来自AI的求助信息。",
                    "外部的怜悯",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
            }

            BtnAssist.Content = n > 0 ? $"外部的怜悯 · {n}" : "外部的怜悯";
            BtnAssist.Background = n > 0 ? Theme.Brush("#FDEDED") : Theme.Blue;
            BtnAssist.Foreground = n > 0 ? Theme.Red : Brushes.White;
        }
        catch
        {
            // assist 通道不可用不影响主界面
        }
    }

    // ==================== 渲染 ====================

    private void Render(WatchState st)
    {
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
        // 侧栏这一行仍然用、分隔：空间紧的地方拆成两行不好看，但语义上已是两个独立事件。
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

        TxtRisk.Text = $"{mddTxt}|{shp}";

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
        BtnHoldMore.Visibility = st.Positions.Count >= 2 ? Visibility.Visible : Visibility.Collapsed;

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

        // 不截断：活动流要能回看到开局第一条。渲染侧已经是虚拟化列表，
        // 主窗右栏本来就只画最近 30 条，内存里留全量不会拖慢界面。

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
            "open" => Theme.LogTradeHex,
            "close" => Theme.LogCloseHex,
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
