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
    private ScratchWindow? _scratchWindow;
    private LogWindow? _logWindow;
    private HoldWindow? _holdWindow;

    private bool _closing;
    private bool _busy;

    // ---------- 一大波预警 ----------
    // 引擎只在预警那一 tick 把 huge_wave.show 置真，下一 tick 就翻回 false。
    // 用 tick 号记录「已经为哪一 tick 播过」，防止两件事：
    //   ① 轮询慢于 tick 推进时同一条预警被连续两帧读到（会重复播音效）；
    //   ② 用户把窗口最小化再还原、界面重建时重播。
        private bool _hugeWaveShowLatch;   // 上一次渲染时 show 的值，用于取上升沿

    // 出场动画的两个时长（毫秒），只在这里改。
    // 参考：PvZ 原版文字缩放到位实测是 200ms（60fps 下 12 帧），但那是 800×600 的画面；
    // 放到 1920 宽的观众席上观感偏急，按用户反馈放慢到 620/260。
    // 注意 hugewave.ogg 本身长 6.5709 秒，那是「音效 + 停留」的总长，不是缩放时长，
    // 横幅停留时间由下面的 10 秒定时器控制，已经覆盖。
    private const int HugeWaveScaleMs = 620;
    private const int HugeWaveFadeMs = 260;

    private DispatcherTimer? _hugeWaveTimer;
    private readonly SoundPlayer _hugeWavePlayer = new();
    private bool _hugeWaveAudioReady;

    public MainWindow()
    {
        InitializeComponent();

        // 按显示器可用区域挑尺寸：2K 及以上 1920×1080，1080p 换 1600×900（观察员反馈固定
        // 1920×1080 在 1080p 屏上顶满整屏）。XAML 里的 1920×1080 只是设计基准与设计器预览。
        var prof = DisplayProfile.Pick();
        try
        {
            System.IO.File.AppendAllText(
                System.IO.Path.Combine(System.IO.Path.GetTempPath(), "TokensWatch.size.log"),
                string.Format("{0:HH:mm:ss} TM_WATCH_SIZE='{1}' -> {2} {3:0}x{4:0}{5}",
                              DateTime.Now,
                              Environment.GetEnvironmentVariable("TM_WATCH_SIZE") ?? "",
                              prof.Label, prof.Width, prof.Height, Environment.NewLine));
        }
        catch { }
        Width = prof.Width;
        Height = prof.Height;
        // 标题带上档位：观察员反馈分辨率问题时，截图里就能看出用的是哪一档。
        Title = string.Format("{0} [{1}]", Title, prof.Label);
        if (ColRight is not null)
            ColRight.Width = new GridLength(prof.RightColumn);

        BuildPriceGrid();

        _uiTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(PollMs) };
        // async void 是 WPF 里唯一会让异常逃出 Task 边界的形式；这里自己兜住，
        // 免得它升到 App 的全局处理器变成「弹一次就退出」。
        _uiTimer.Tick += async (_, _) =>
        {
            try { await PollAsync(); }
            catch (Exception ex) { TxtRunState.Text = "刷新异常：" + ex.Message; }
        };

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
            // 首帧失败和**中途**失败都必须改状态条：只在 _state 为 null 时提示的话，
            // 一旦首帧成功过，后面断线界面会一直显示最后一帧的报价与倒计时，
            // 玩家会拿过期数据判断局面——这比直接崩更糟。
            string msg = ex.Message.Replace("\r", " ").Replace("\n", " ");
            if (msg.Length > 80) msg = msg[..80] + "…";
            TxtRunState.Text = (_state is null ? "连接失败：" : "连接中断：") + msg;
            TxtRunState.Foreground = Theme.Red;
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
        // ---------- 一大波预警（PvZ 演出移植）----------
        // 放在最前面：预警是全屏级事件，任何其它数据都不该抢先写它。
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

        // 按字段判定，不要靠文案关键词匹配：文案是本地化层，判色是逻辑层，
        // 用字符串匹配会在下一次改文案时静默失效，而且「已爆仓」「本局已结束」
        // 这两种最该警示的状态原本根本不在关键词表里，被渲染成正常的灰色。
        bool danger = st.Blowups > 0
                      || st.Finished
                      || st.Tampered
                      || st.ClockCheat
                      || st.Unnamed
                      || st.NegativeRemain is not null
                      || st.MarginCallRemain is not null
                      || (st.MarginLevel is { } mlv2 && mlv2 < 50);
        TxtRunState.Foreground = danger ? Theme.Red : Theme.Muted;

        // ---------- 统计行 ----------
        string mddTxt = st.MaxDrawdown is { } mdd ? $"{mdd:0.00}%" : "—";
        string shp = st.Sharpe is { } s ? s.ToString("0.00", CultureInfo.CurrentCulture) : "—";
        // 盈利因子（总盈利 / 总亏损）取代胜率：有杠杆、一大波和强平，一笔亏损就能
        // 吞掉十几笔小赢，单看赢的笔数几乎说明不了权益最终会落在哪里。
        string pf = st.ProfitFactor is { } pfv
            ? pfv.ToString("0.00", CultureInfo.CurrentCulture)
            : (st.ClosedN > 0 && st.WinN == st.ClosedN ? "∞" : "—");
        double fee = st.Fees + st.Swap;

        TxtStats.Text = $"目标 {st.Target:N0}" +
                        (st.TargetBonus > 0 ? $"（贷款上浮 +{st.TargetBonus:N0}）" : "") +
                        $" | 回撤 {mddTxt} | 夏普 {shp} | {st.ClosedN} 笔 · 盈利因子 {pf} | 费息 {fee:N0}";

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
    /// 一大波预警的渲染入口。
    /// 引擎侧 _roll_huge_wave() 是三段式：预警 tick 把 show 置真 → 静默 2 tick → 成批爆发。
    /// 这里只负责第一段「出横幅 + 播音效」；第三段爆发走的是普通事件流，由活动流展示。
    /// </summary>
    private void RenderHugeWave(WatchState st)
    {
        var hw = st.HugeWave;
        if (hw is null) { _hugeWaveShowLatch = false; return; }   // 老引擎不返回该字段：当作本局没有预警

        // 只处理「该出场」的那一 tick。收起交给 ShowHugeWave 起的 10 秒定时器，
        // 不靠 show 翻回 false 来收 —— 否则下一 tick（5 秒后）横幅就被自己掐掉，
        // 演出时长会缩水成半截，音效还在响画面已经没了。
        // 只在 show 的「上升沿」播一次。引擎侧理论上只把一个 tick 的 show 置真，
        // 但实测数据源连续两个 tick 都返回 show=true 时，按 tick 去重会连播第二遍
        // （用户实测就撞到过）。上升沿用布尔锁存判断，与 tick 编号无关，最稳。
        bool rising = hw.Show && !_hugeWaveShowLatch;
        _hugeWaveShowLatch = hw.Show;
        if (!rising) return;

        ShowHugeWave(string.IsNullOrWhiteSpace(hw.Text) ? "一大波异常行情正在接近！" : hw.Text);
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
            string reason = "本局游戏参赛者未开启挑战任务";
            // off 且带过理由时，引擎会在 events 里写；卡片本身保持固定一句话，
            // 免得同一句文案在两个地方各写一遍还要对不上。
            TxtChallengeHint.Text = reason;
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "";
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
        }
    }

    private static Brush BrushOf(string hex) =>
        new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));

    private UIElement BuildChallengeRow(ChallengeTask t)
    {
        var grid = new Grid { Margin = new Thickness(0, 0, 0, 9) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        string mark;
        string hex;
        switch (t.Status)
        {
            case "done": mark = "√"; hex = Theme.GreenHex; break;   // √
            case "failed": mark = "×"; hex = Theme.RedHex; break;  // ×
            default: mark = "·"; hex = Theme.MutedHex; break;      // ·
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
        // 描边层与本体必须逐字一致，否则两层会错位成「重影」
        HugeWaveText.Text = text;
        HugeWaveOutline.Text = text;
        HugeWaveLayer.Visibility = Visibility.Visible;

        // ---- 出现动画：由大到小等比收拢 + 淡入 ----
        // 起始 1.55 倍，收拢到 1.0 定住；时长取 HugeWaveScaleMs / HugeWaveFadeMs 两个常量。
        // 数值来自原版录像逐帧测量：34.083s 出现 → 34.283s 到位（12 帧），
        // 峰值宽度约 1.5 倍成品宽，且底边 y=354 全程不动。
        // ScaleX 与 ScaleY 同步，等比缩放，字不会被压扁。
        var easeOut = new CubicEase { EasingMode = EasingMode.EaseOut };

        HugeWaveBanner.BeginAnimation(UIElement.OpacityProperty,
            new DoubleAnimation(0.0, 1.0, TimeSpan.FromMilliseconds(HugeWaveFadeMs)) { EasingFunction = easeOut });

        HugeWaveScale.BeginAnimation(ScaleTransform.ScaleXProperty,
            new DoubleAnimation(1.55, 1.0, TimeSpan.FromMilliseconds(HugeWaveScaleMs)) { EasingFunction = easeOut });

        HugeWaveScale.BeginAnimation(ScaleTransform.ScaleYProperty,
            new DoubleAnimation(1.55, 1.0, TimeSpan.FromMilliseconds(HugeWaveScaleMs)) { EasingFunction = easeOut });

        PlayHugeWaveSound();

        // PvZ 原版横幅在 mHugeWaveCountDown == 0 时 ClearAdvice 消失。
        // 换算到本引擎正好是一个演出期：HUGE_WAVE_WARN_TICKS = 2 tick = 10 秒，
        // 正好包住 hugewave.wav 的 6.57 秒并留约 3.4 秒余韵。
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
        // 收场：淡出，不做硬切（用户已确认这一版消失动画是对的，保持不动）
        var fade = new DoubleAnimation(1.0, 0.0, TimeSpan.FromMilliseconds(220));
        fade.Completed += (_, _) =>
        {
            HugeWaveLayer.Visibility = Visibility.Collapsed;
            // 复位，让下一次重新从 1.55 倍 / 透明开始（否则第二次不会播动画）
            HugeWaveBanner.BeginAnimation(UIElement.OpacityProperty, null);
            HugeWaveBanner.Opacity = 0;
            HugeWaveScale.BeginAnimation(ScaleTransform.ScaleXProperty, null);
            HugeWaveScale.ScaleX = 1.55;
            HugeWaveScale.BeginAnimation(ScaleTransform.ScaleYProperty, null);
            HugeWaveScale.ScaleY = 1.55;
        };
        HugeWaveBanner.BeginAnimation(UIElement.OpacityProperty, fade);
    }

    private void PlayHugeWaveSound()
    {
        if (_hugeWaveAudioReady)
        {
            _hugeWavePlayer.Play();
            return;
        }
        try
        {
            // 音效来自 PvZ 的 main.pak（sounds\hugewave.ogg），已转成 PCM WAV：
            // WPF 的 SoundPlayer 只吃 WAV，而带解码依赖的 MediaPlayer 在干净机器上会静音。
            string path = System.IO.Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory, "Assets", "hugewave.wav");
            if (!System.IO.File.Exists(path)) return;   // 缺资源就只出画面，不影响对局
            _hugeWavePlayer.SoundLocation = path;
            _hugeWavePlayer.LoadAsync();     // 1.1 MB，Play() 会自己等加载完成
            _hugeWaveAudioReady = true;
            _hugeWavePlayer.Play();
        }
        catch
        {
            // 声卡被别的程序独占、音频服务没起，都不该让观众席崩——
            // 横幅才是主体，音效是配角。
        }
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
