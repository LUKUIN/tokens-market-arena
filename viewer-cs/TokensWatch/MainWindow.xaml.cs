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
    // The system accent color paints the title bar red (which is what this machine does),
    // clashing with the overall light-grey card styling. Win11 lets us set the caption color directly.
    private const int DWMWA_CAPTION_COLOR = 35;
    private const int DWMWA_TEXT_COLOR = 36;

    [System.Runtime.InteropServices.DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    // ---- Remove the three system buttons from the title bar top right ----
    // Mirrors _hide_close_button in Python (lines 83-103). Rationale: a stray click on X closes the window
    // and nobody watches the match any more; Minimize still works through the built-in top-bar button.
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

        // 1) Caption color follows the light-grey theme instead of the system accent (red on this machine)
        try
        {
            int caption = 0x00F3F3F3;   // COLORREF is 0x00BBGGRR, not RGB
            DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ref caption, sizeof(int));
            int text = 0x001A1A1A;
            DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ref text, sizeof(int));
        }
        catch
        {
            // Win10 has neither property; keep the system default
        }

        // 2) Drop Minimize / Maximize / Close
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
            // On failure keep the system buttons; nothing else is affected
        }
    }

    private readonly StateClient _client = new();

    // Main loop at 300 ms, mirroring self.root.after(delay, self.refresh) on the Python side
    private readonly DispatcherTimer _uiTimer;
    private const int PollMs = 300;

    // Low-frequency "Outside Mercy" poll, mirroring _poll_assist
    private readonly DispatcherTimer _assistTimer;
    private const int AssistPollMs = 3000;

    private WatchState? _state;

    private readonly List<GameEvent> _logEvents = new();
    private readonly HashSet<(int Tick, string Text)> _logSeen = new();
    private readonly HashSet<string> _assistSeen = new();

    /// <summary>Activity filter. The main window and the "Activity (all)" popup share this state,
    /// mirroring self._log_filter in Python: switching a category in the popup changes the newest line outside too.</summary>
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

    // ---------- Huge Wave warning ----------
    // The engine raises huge_wave.show for the warning tick only and drops it on the next
    // one. Keying on the tick number prevents two things:
    //   1) the same warning being read on two consecutive polls (which would replay the
    //      sound) when polling is slower than the tick clock;
    //   2) a replay after the window is minimised and restored and the UI is rebuilt.
        private bool _hugeWaveShowLatch;   // last rendered show value, used to detect the rising edge

    // The two exit-animation durations in milliseconds; change them only here.
    // Reference: the PvZ original scales its text in 200 ms (12 frames at 60 fps), but that is an 800x600 screen;
    // on a 1920-wide spectator it reads as rushed, so feedback moved it to 620/260.
    // Note hugewave.ogg itself runs 6.5709 s: that is "sound + hold", not the scale duration,
    // and the banner hold is driven by the 10-second timer below, which already covers it.
    private const int HugeWaveScaleMs = 620;
    private const int HugeWaveFadeMs = 260;

    private DispatcherTimer? _hugeWaveTimer;
    private readonly SoundPlayer _hugeWavePlayer = new();
    private bool _hugeWaveAudioReady;


    public MainWindow()
    {
        InitializeComponent();

        // Pick a size from the display work area: 1920x1080 at 2K and above, 1600x900 on 1080p (observers reported
        // a fixed 1920x1080 filling the whole 1080p screen). The 1920x1080 in XAML is only the design baseline.
        var prof = DisplayProfile.Pick();
        Width = prof.Width;
        Height = prof.Height;
        if (ColRight is not null)
            ColRight.Width = new GridLength(prof.RightColumn);

        BuildPriceGrid();

        _uiTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(PollMs) };
        // async void is the one place a WPF exception escapes the Task boundary; keep it
        // inside so it never reaches the global handler and turns into a hard exit.
        _uiTimer.Tick += async (_, _) =>
        {
            try { await PollAsync(); }
            catch (Exception ex) { TxtRunState.Text = "Refresh error: " + ErrorText.Describe(ex); }
        };

        _assistTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(AssistPollMs) };
        _assistTimer.Tick += async (_, _) => await PollAssistAsync();

        Loaded += (_, _) =>
        {
            // Design baseline is 1920x1080. This machine has a 2K panel, so it fits normally;
            // at 150% system scaling, though, 1920 DIP exceeds 2560 physical pixels,
            // so clamp here and make sure the window never lands off screen.
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

    // ==================== Polling ====================

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
            // Service not started / restarted mid-match / deserialization failure all land here.
            // Both the first frame and a **mid-match** failure must update the status bar: guarding
            // on _state == null means that once the first frame succeeds, a later disconnect leaves
            // stale prices and countdown on screen with no hint at all — worse than crashing.
            string msg = ErrorText.Describe(ex);
            if (msg.Length > 80) msg = msg[..80] + "...";
            TxtRunState.Text = (_state is null ? "Connection failed: " : "Connection lost: ") + msg;
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

                // Mirrors Python lines 584-594: a new ask rings the chime and raises the popup.
                // Without this, a player busy elsewhere misses the ask window entirely.
                System.Media.SystemSounds.Asterisk.Play();

                string cn = n switch { 1 => "one", 2 => "two", 3 => "three", _ => n.ToString() };
                MessageBox.Show(
                    this,
                    $"You have {cn} assistance request(s) from the AI.",
                    "Outside Mercy",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
            }

            BtnAssist.Content = n > 0 ? $"Outside Mercy · {n}" : "Outside Mercy";
            BtnAssist.Background = n > 0 ? Theme.Brush("#FDEDED") : Theme.Blue;
            BtnAssist.Foreground = n > 0 ? Theme.Red : Brushes.White;
        }
        catch
        {
            // An unavailable assist channel never affects the main UI
        }
    }

    // ==================== Rendering ====================

    private void Render(WatchState st)
    {
        // ---------- Huge Wave warning (PvZ port) ----------
        // First, because it is a full-screen event: nothing else may outrank it.
        RenderHugeWave(st);

        // ---------- challenge tasks (PvZ2 Level Objectives port) ----------
        RenderChallenge(st);

        // ---------- Top bar ----------
        TxtTrader.Text = string.IsNullOrEmpty(st.Trader) ? "Guest" : st.Trader;
        TxtMode.Text = st.EventsOn ? "Random events ON" : "Ideal (no random events)";
        TxtMode.Foreground = st.EventsOn ? Theme.Blue : Theme.Muted;

        // One chip per global event: show the ones that are on, never joined.
        bool fr = st.Special?.Fr == true;
        bool slot = st.Special?.Slot == true;
        ChipFr.Visibility = fr ? Visibility.Visible : Visibility.Collapsed;
        ChipSlot.Visibility = slot ? Visibility.Visible : Visibility.Collapsed;
        ChipSpecial.Visibility = (fr || slot) ? Visibility.Collapsed : Visibility.Visible;

        // ---------- Metric cards ----------
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

        // ---------- Funds row ----------
        var loan = st.Loan;
        string rateTxt = loan is null ? "—" : $"{loan.RatePct:0.000}%/tick";
        TxtFunds.Text = loan is null
            ? $"Available — | Cash {st.Balance:N0}"
            : $"Available {loan.Limit:N0} | Cash {st.Balance:N0} | Borrowed {st.TotalBorrowed:N0} | " +
              $"Debt {loan.Balance:N0} | Interest {loan.Interest:N0} | {rateTxt}";
        TxtFunds.Foreground = st.TotalBorrowed > 0 ? Theme.Red : Theme.Blue;

        // ---------- Status text ----------
        string stateTxt = "Trading normally";
        if (st.NegativeRemain is { } nr)
            stateTxt = $"Balance negative · {(int)nr}s to borrow or the round ends";
        else if (st.Tampered)
            stateTxt = "Save tampered · reset";
        else if (st.ClockCheat)
            stateTxt = "Clock rolled back · timer frozen";
        else if (st.MarginCallRemain is { } mcr)
            stateTxt = $"Margin call · {(int)mcr} ticks left";
        else if (st.Unnamed)
            stateTxt = "Unnamed launch · use Start Match.bat";
        else if (st.MarginLevel is { } mlv && mlv < 50)
            stateTxt = "Margin level critical";
        else if (st.Blowups > 0 && st.MarginLevel is null)
            stateTxt = $"Blown up {st.Blowups}×";

        if (st.Finished) stateTxt = "Round finished";

        int elapsed = (int)Math.Max(0, st.ElapsedSeconds);
        int mm = elapsed / 60, ss = elapsed % 60;

        string mods = st.ActiveModsText();
        TxtRunState.Text = $"{stateTxt} | {mm:00}:{ss:00} | orders {st.OrderCount}" +
                           (mods.Length > 0 ? "  |  " + mods : "");

        // Decide by field, not by matching the localised text: the label is presentation,
        // the colour is logic. String matching silently breaks on the next wording change,
        // and it previously missed "blown up" and "match finished" entirely.
        bool danger = st.Blowups > 0
                      || st.Finished
                      || st.Tampered
                      || st.ClockCheat
                      || st.Unnamed
                      || st.NegativeRemain is not null
                      || st.MarginCallRemain is not null
                      || (st.MarginLevel is { } mlv2 && mlv2 < 50);
        TxtRunState.Foreground = danger ? Theme.Red : Theme.Muted;

        // ---------- Statistics row ----------
        string mddTxt = st.MaxDrawdown is { } mdd ? $"{mdd:0.00}%" : "—";
        string shp = st.Sharpe is { } s ? s.ToString("0.00", CultureInfo.CurrentCulture) : "—";
        // Profit factor (gross profit / gross loss) replaces the win rate here: with leverage,
        // Huge Waves and forced liquidations, one loss can swallow a dozen small wins, so the
        // ratio of winning trades barely predicts where the equity line ends up.
        string pf = st.ProfitFactor is { } pfv
            ? pfv.ToString("0.00", CultureInfo.CurrentCulture)
            : (st.ClosedN > 0 && st.WinN == st.ClosedN ? "∞" : "—");
        double fee = st.Fees + st.Swap;

        TxtStats.Text = $"Target {st.Target:N0}" +
                        (st.TargetBonus > 0 ? $" (loan uplift +{st.TargetBonus:N0})" : "") +
                        $" | Drawdown {mddTxt} | Sharpe {shp} | {st.ClosedN} trades · profit factor {pf} | fees {fee:N0}";

        // ---------- Fast forward ----------
        if (st.Ff is { } ff)
        {
            double usedSum = ff.Records.Sum();
            string txt = "FF left " + FmtFf(ff.Remain);
            if (ff.Records.Count > 0) txt += " | used " + FmtFf(usedSum);
            if (ff.CoolLeft > 0) txt += $" | cooldown {(int)Math.Ceiling(ff.CoolLeft)}s";
            TxtFastForward.Text = txt;
            TxtFastForward.Foreground = ff.CoolLeft > 0 ? Theme.Red : Theme.Muted;
        }

        // ---------- Time progress ----------
        double total = Math.Max(1, st.SessionMinutes * 60.0);
        double frac = Math.Clamp(st.ElapsedSeconds / total, 0, 1);
        double remain = Math.Max(0, total - st.ElapsedSeconds);
        if (BarTime.Parent is FrameworkElement track && track.ActualWidth > 0)
            BarTime.Width = Math.Max(0, track.ActualWidth * frac);
        BarTime.Background = frac < 0.8 ? Theme.Blue : Theme.Orange;
        TxtTimeLeft.Text = $"Left {(int)remain / 60:00}:{(int)remain % 60:00}";
        TxtTimeLeft.Foreground = frac < 0.8 ? Theme.Muted : Theme.Orange;

        // ---------- Status panel ----------
        TxtAudit.Text = st.Audit.Count > 0 ? $"{st.Audit.Count} warnings" : "passed (4 identities)";
        TxtAudit.Foreground = st.Audit.Count > 0 ? Theme.Red : Theme.Green;

        string gapPct = st.GapLevel is not null && Theme.GapPct.TryGetValue(st.GapLevel, out var gp) ? gp : "?";
        TxtGap.Text = $"{st.GapLevel ?? "—"} ({gapPct}/tick)";

        string liqPct = st.LiqLevel is not null && Theme.LiqPct.TryGetValue(st.LiqLevel, out var lp) ? lp : "?";
        TxtLiq.Text = $"{st.LiqLevel ?? "—"} ({liqPct} round-trip)";

        TxtFf.Text = st.Ff is null ? "—" : FmtFf(st.Ff.Remain);
        var specialNames = new List<string>();
        if (fr) specialNames.Add(Theme.FrName);
        if (slot) specialNames.Add(Theme.SlotName);
        TxtSpecialState.Text = specialNames.Count > 0 ? string.Join(", ", specialNames) : "None";

        // Peak / Trough: read the extremes straight off the curve so they match the chart annotations.
        // With only 1 point (right after the open) there is no "movement": peak and trough would equal
        // the Principal, which reads as "zero volatility all match" and disagrees with the chart "No data",
        // so both use a threshold of 2 and stay consistent with the curve.
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
            : string.Format("Total {0} | fired {1} | pending {2}", hwi.Total, hwi.Fired, hwi.Left);

        // ---------- Curve ----------
        ChartEquity.SetData(st.EquityCurve, baseLine: 1_000_000, target: st.Target);

        // ---------- Positions ----------
        RenderPositions(st);

        // ---------- Quotes ----------
        RenderPrices(st);

        // ---------- Activity ----------
        AppendEvents(st);

        // ---------- Child windows follow the main loop ----------
        RefreshHoldPanel();
    }

    private void RenderPositions(WatchState st)
    {
        HoldRows.Children.Clear();

        if (st.Positions.Count == 0)
        {
            // Empty-state collapse: draw no header, just one hint line, so 260 px are not left blank
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
            row.Children.Add(Cell(p.Side == "LONG" ? "Long" : "Short",
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

            // At 7 columns each cell is only about 200 px: instrument, price and change on one line get clipped,
            // so the layout splits into a "name + change" row and a "price" row.
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

        // Never truncate: the activity feed must scroll back to the very first entry. The renderer is already virtualized,
        // and the right column only draws the latest 30 entries, so keeping the full list in memory costs nothing.

        RenderLogFeed();
        _logWindow?.AppendAll(_logEvents);
    }

    /// <summary>
    /// Right-column activity: newest on top, at most 30 rendered, the rest via scrolling.
    /// The original main window showed the latest single line, giving a whole block to one row; this fills the space.
    /// </summary>
    /// <summary>Called back by the "Activity (all)" popup so the filter is identical inside and out.</summary>
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
    /// Challenge card. Four stages:
    ///   none -- not rolled yet, shown as not enabled;
    ///   ask  -- waiting for the contestant, candidates listed with a countdown;
    ///   on   -- enabled, each row shows check / cross / dot;
    ///   off  -- the contestant declined.
    /// The engine owns judging; this only draws what it reports.
    /// </summary>
    private void RenderChallenge(WatchState st)
    {
        var ch = st.Challenge;
        ChallengeList.Children.Clear();

        string stage = ch?.Stage ?? "none";
        if (ch is null || (stage != "ask" && stage != "on"))
        {
            TxtChallengeHint.Text = "The contestant did not enable challenge tasks";
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "";
            return;
        }

        foreach (var t in ch.Tasks)
            ChallengeList.Children.Add(BuildChallengeRow(t));

        if (stage == "ask")
        {
            TxtChallengeHint.Text = string.Format(
                "Waiting for the contestant to decide... ({0:0}s left, runs without tasks on timeout)", ch.AskLeft);
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "Pending";
        }
        else if (ch.Tasks.Count == 0)
        {
            TxtChallengeHint.Text = "Enabled; three objectives will appear once the difficulty is locked";
            TxtChallengeHint.Visibility = Visibility.Visible;
            TxtChallengeCount.Text = "Pending";
        }
        else
        {
            TxtChallengeHint.Visibility = Visibility.Collapsed;
            TxtChallengeCount.Text = string.Format("{0}/{1} cleared", ch.Cleared, ch.Total);
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
        // hugewave.wav (6.57 s) in full and leaves about 3.4 s of tail.
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

    private void PlayHugeWaveSound()
    {
        if (_hugeWaveAudioReady)
        {
            _hugeWavePlayer.Play();
            return;
        }
        try
        {
            // The clip is the original hugewave.ogg from PvZ's main.pak (sounds\hugewave.ogg,
            // 111,507 B, 44.1 kHz stereo, 6.57 s), transcoded to PCM WAV: SoundPlayer only
            // reads WAV, and MediaPlayer with an Ogg codec dependency goes silent on a clean
            // machine. 1.1 MB buys "it always makes a sound".
            string path = System.IO.Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory, "Assets", "hugewave.wav");
            if (!System.IO.File.Exists(path)) return;   // missing asset: show the banner anyway
            _hugeWavePlayer.SoundLocation = path;
            _hugeWavePlayer.LoadAsync();     // 1.1 MB; Play() waits for the load itself
            _hugeWaveAudioReady = true;
            _hugeWavePlayer.Play();
        }
        catch
        {
            // Exclusive-mode audio, or the audio service not running, must never take the
            // viewer down -- the banner is the substance, the sound is the garnish.
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
                Text = "Waiting for events…",
                FontSize = 13,
                Foreground = Theme.Muted,
            });
        }
    }

    private static string KindColor(string kind, string text)
    {
        // Mirrors kind_color in the Python _write_rows; the black-swan bucket must pull out "Liquidity drained"
        if (kind == "gap")
        {
            bool isLiq = text.Contains("Liquidity drained") || text.Contains("Liquidity drained");
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
        return $"{s / 60}m {s % 60:00}s";
    }

    // ==================== Top-bar buttons ====================

    private void OnMinimizeClick(object sender, RoutedEventArgs e)
        => WindowState = WindowState.Minimized;

    private void OnQuitClick(object sender, RoutedEventArgs e)
    {
        var r = MessageBox.Show(
            "This also stops the match service and records an abnormal exit.\n\nEnd it anyway?",
            "Stop related processes",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);

        if (r != MessageBoxResult.Yes) return;

        try
        {
            // Same semantics as the Python-side "Stop related processes" button: let the service wind itself down first
            _ = _client.PostShutdownAsync();
        }
        catch
        {
            // Fine if the service is already gone
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

    /// <summary>The Positions popup refreshes with the main loop, driven by it.</summary>
    public void RefreshHoldPanel()
    {
        if (_holdWindow is { IsLoaded: true } && _state is not null)
            _holdWindow.UpdateRows(_state.Positions);
    }
}
