using System.Globalization;
using System.Windows;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 「投资」交易面板。对应 tm_watch_ai.py 人类版的 _open_trade_panel / _tp_refresh / _tp_do_*。
///
/// 与原版一致的三条行为：
///  1. 不允许点 X 关闭（原版 protocol("WM_DELETE_WINDOW", lambda: None)），只能按「关闭窗口」；
///  2. 内容可滚动，窗口高度不够时不裁掉底部按钮；
///  3. 下单/平仓/借贷/快进都只发 HTTP，不本地改账本——账本永远以 /state 为准。
/// </summary>
public partial class TradeWindow : Window
{
    private readonly StateClient _client;
    private WatchState? _state;

    public TradeWindow(StateClient client)
    {
        InitializeComponent();
        _client = client;

        foreach (var p in Theme.PairOrder)
            CmbPair.Items.Add(p);
        CmbPair.SelectedIndex = 0;

        SourceInitialized += (_, _) => WindowChrome.Apply(this);
    }

    // ==================== 数据推送 ====================

    public void UpdateState(WatchState st)
    {
        _state = st;
        RenderInfo(st);
        RenderLoan(st);
        RenderFastForward(st);
        RenderPositions(st);
    }

    private void RenderInfo(WatchState st)
    {
        double margin = st.Positions.Sum(p => p.Margin);
        string ml = st.MarginLevel is { } v ? $"{v:0.0}%" : "—";
        TxtInfo.Text = $"账户权益 {st.Equity:N0}   |   保证金占用 {margin:N0}   |   " +
                       $"保证金水平 {ml}   |   tick {st.Tick}";
    }

    private void RenderLoan(WatchState st)
    {
        if (st.Loan is not { } loan)
        {
            TxtLoan.Text = "—";
            return;
        }

        string ev = string.IsNullOrEmpty(st.LoanPoolEvent) ? "" : $"（{st.LoanPoolEvent}）";
        TxtLoan.Text = loan.Balance > 0
            ? $"可贷 {loan.Limit:N0}{ev}   |   已借 {loan.Balance:N0}   |   " +
              $"累计利息 {loan.Interest:N0}（每 tick 按欠款 {loan.RatePct:0.000}% 滚入本金）"
            : $"可贷 {loan.Limit:N0}{ev}   |   当前无欠款";
    }

    private void RenderFastForward(WatchState st)
    {
        if (st.Ff is not { } ff)
        {
            BtnFf5.IsEnabled = BtnFf3.IsEnabled = false;
            TxtFfHint.Text = "";
            return;
        }

        double usedSum = ff.Records.Sum();
        bool cooling = ff.CoolLeft > 0;

        BtnFf5.IsEnabled = !cooling && ff.Remain >= 300;
        BtnFf3.IsEnabled = !cooling && ff.Remain >= 180;

        if (cooling)
            TxtFfHint.Text = $"冷却中 {(int)Math.Ceiling(ff.CoolLeft)} 秒 | 剩余 {FmtFf(ff.Remain)} | 已用 {FmtFf(usedSum)}";
        else if (ff.Remain <= 0)
            TxtFfHint.Text = $"额度已用完（已用 {FmtFf(usedSum)}）";
        else
            TxtFfHint.Text = $"剩余 {FmtFf(ff.Remain)} | 已用 {FmtFf(usedSum)}";
    }

    private void RenderPositions(WatchState st)
    {
        var rows = st.Positions.Select(p => new TradeRowVm(p)).ToList();

        var selected = HoldList.SelectedItem as TradeRowVm;
        HoldList.ItemsSource = rows;
        if (selected is not null)
        {
            HoldList.SelectedItem = rows.FirstOrDefault(row =>
                row.Pair == selected.Pair && row.SideCode == selected.SideCode);
        }

        TxtHoldEmpty.Visibility = rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        HoldList.Visibility = rows.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    private static string FmtFf(double sec)
    {
        int s = (int)Math.Round(Math.Max(0, sec));
        return $"{s / 60} 分 {s % 60:00} 秒";
    }

    // ==================== 操作 ====================

    private async void OnOpenClick(object sender, RoutedEventArgs e)
    {
        string pair = CmbPair.SelectedItem as string ?? Theme.PairOrder[0];
        string side = RdoShort.IsChecked == true ? "SHORT" : "LONG";

        if (!int.TryParse(TxtLots.Text.Trim(), out int lots) || lots <= 0)
        {
            Say("手数必须是正整数", Theme.Red);
            return;
        }
        if (!int.TryParse(TxtLeverage.Text.Trim(), out int lev) || lev < 1 || lev > 1000)
        {
            Say("杠杆必须在 1~1000 之间", Theme.Red);
            return;
        }

        var (ok, err) = await _client.OpenAsync(pair, side, lots, lev);
        Say(ok ? $"已下单：{pair} {(side == "LONG" ? "做多" : "做空")} {lots} 手 ×{lev}"
               : (string.IsNullOrEmpty(err) ? "下单失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnCloseClick(object sender, RoutedEventArgs e)
    {
        if (HoldList.SelectedItem is not TradeRowVm vm)
        {
            Say("先在上面选一行持仓", Theme.Orange);
            return;
        }

        var (ok, err) = await _client.CloseAsync(vm.Pair, vm.SideCode);
        Say(ok ? $"已平仓：{vm.Pair}（{vm.Side}）"
               : (string.IsNullOrEmpty(err) ? "平仓失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnCloseAllClick(object sender, RoutedEventArgs e)
    {
        var (ok, err) = await _client.CloseAllAsync();
        Say(ok ? "已全部平仓" : (string.IsNullOrEmpty(err) ? "全部平仓失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnLoanClick(object sender, RoutedEventArgs e)
    {
        if (!double.TryParse(TxtAmount.Text.Trim(), out double amt) || amt <= 0)
        {
            Say("金额必须是正数", Theme.Red);
            return;
        }

        var (ok, err) = await _client.LoanAsync(amt);
        Say(ok ? $"已借款 {amt:N0}" : (string.IsNullOrEmpty(err) ? "借款失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnRepayClick(object sender, RoutedEventArgs e)
    {
        if (!double.TryParse(TxtAmount.Text.Trim(), out double amt) || amt <= 0)
        {
            Say("金额必须是正数", Theme.Red);
            return;
        }

        var (ok, err) = await _client.RepayAsync(amt);
        Say(ok ? $"已还款 {amt:N0}" : (string.IsNullOrEmpty(err) ? "还款失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnFf5Click(object sender, RoutedEventArgs e)
        => await DoFastForward(300);

    private async void OnFf3Click(object sender, RoutedEventArgs e)
        => await DoFastForward(180);

    private async Task DoFastForward(int seconds)
    {
        var (ok, err) = await _client.FastForwardAsync(seconds);
        Say(ok ? $"已快进 {seconds / 60} 分钟"
               : (string.IsNullOrEmpty(err) ? "快进失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnResetClick(object sender, RoutedEventArgs e)
    {
        var r = MessageBox.Show(this,
            "重开一局会丢弃当前进度。确定吗？",
            "重开一局", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
        if (r != MessageBoxResult.Yes) return;

        var (ok, err) = await _client.ResetAsync();
        Say(ok ? "已重开一局" : (string.IsNullOrEmpty(err) ? "重开失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private async void OnQuitClick(object sender, RoutedEventArgs e)
    {
        var r = MessageBox.Show(this,
            "结束并结算：净值已达标但仍有持仓时会被拒绝，需要先全部平仓。\n\n确定要结束吗？",
            "结束并结算", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
        if (r != MessageBoxResult.Yes) return;

        var (ok, err) = await _client.QuitAsync();
        if (ok && !string.IsNullOrEmpty(err))
            MessageBox.Show(this, err, "战报补导", MessageBoxButton.OK, MessageBoxImage.Warning);
        Say(ok ? "已提交结算" : (string.IsNullOrEmpty(err) ? "结算失败" : err),
            ok ? Theme.Green : Theme.Red);
    }

    private void OnCloseWindowClick(object sender, RoutedEventArgs e) => Close();

    // 快捷杠杆
    private void OnQuickLev1(object sender, RoutedEventArgs e) => TxtLeverage.Text = "1";
    private void OnQuickLev10(object sender, RoutedEventArgs e) => TxtLeverage.Text = "10";
    private void OnQuickLev50(object sender, RoutedEventArgs e) => TxtLeverage.Text = "50";
    private void OnQuickLev100(object sender, RoutedEventArgs e) => TxtLeverage.Text = "100";
    private void OnQuickLev1000(object sender, RoutedEventArgs e) => TxtLeverage.Text = "1000";

    private void Say(string text, Brush color)
    {
        TxtMsg.Text = text;
        TxtMsg.Foreground = color;
    }
}

/// <summary>持仓行视图：把 Position 转成可直接显示的字符串与配色。</summary>
public sealed class TradeRowVm
{
    public string Pair { get; }
    public string SideCode { get; }
    public string Side { get; }
    public string Lots { get; }
    public string Leverage { get; }
    public string Entry { get; }
    public string Price { get; }
    public string Upnl { get; }

    public Brush PairBrush { get; }
    public Brush SideBrush { get; }
    public Brush UpnlBrush { get; }

    public TradeRowVm(Position p)
    {
        Pair = p.Pair;
        SideCode = p.Side;
        Side = SideCode == "LONG" ? "多" : "空";
        Lots = p.Lots.ToString("0.##", CultureInfo.CurrentCulture);
        Leverage = p.Leverage.ToString("0", CultureInfo.CurrentCulture) + "x";
        Entry = p.Entry.ToString("0.##", CultureInfo.CurrentCulture);
        Price = p.Price.ToString("0.##", CultureInfo.CurrentCulture);
        Upnl = p.Upnl.ToString("+#,0;-#,0;0", CultureInfo.CurrentCulture);

        PairBrush = Theme.Brush(Theme.PairColor(p.Pair));
        SideBrush = p.Side == "LONG" ? Theme.Green : Theme.Red;
        UpnlBrush = p.Upnl >= 0 ? Theme.Green : Theme.Red;
    }
}
