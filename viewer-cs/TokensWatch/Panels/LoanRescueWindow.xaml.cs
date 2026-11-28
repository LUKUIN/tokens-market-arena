using System.Globalization;
using System.Windows;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 负资产「贷款自救」窗口。对应 tm_watch_ai.py 人类版第 979-1101 行。
///
/// 三条不可省的行为：
///  1. 置顶且不给关闭按钮——只有「确认借款」「否，终止游戏」两个出口；
///  2. 默认金额填「刚好补平到 0」（-cash + 1，且不超过可借额度），省得玩家心算；
///  3. 倒计时由主循环推送（_loan_left 的等价物），窗口自己不轮询。
/// </summary>
public partial class LoanRescueWindow : Window
{
    private readonly StateClient _client;
    private WatchState _state;
    private bool _busy;
    private bool _allowClose;

    public LoanRescueWindow(StateClient client, WatchState state)
    {
        InitializeComponent();
        _client = client;
        _state = state;

        SourceInitialized += (_, _) => WindowChrome.Apply(this);

        // 不给退路：Alt+F4 也拦下，只有两个按钮能离开
        // （系统按钮已被 WindowChrome.Apply 移除，这里再兜一层键盘关闭）
        Closing += (_, e) =>
        {
            if (!_allowClose) e.Cancel = true;
        };

        UpdateState(state);
        Loaded += (_, _) =>
        {
            TxtAmount.Focus();
            TxtAmount.SelectAll();
        };
    }

    public void UpdateState(WatchState st)
    {
        _state = st;

        double cash = st.Balance;
        double limit = st.Loan?.Limit ?? 0;

        TxtCash.Text = $"所持 Tokens 已跌破 0：{cash:0.00}";
        TxtLimit.Text = limit > 0 ? $"可借额度  {limit:N0}" : "可借额度  —";

        int remain = (int)Math.Max(0, st.NegativeRemain ?? 0);
        TxtRemain.Text = $"{remain} 秒";
        Title = $"资金告负 · 是否借款（剩余 {remain} 秒）";

        // 只在玩家还没改过金额时更新默认值，避免把输入冲掉
        if (string.IsNullOrWhiteSpace(TxtAmount.Text))
        {
            double dflt = limit > 0 ? Math.Max(1.0, Math.Min(limit, -cash + 1)) : 0;
            if (dflt > 0) TxtAmount.Text = dflt.ToString("0", CultureInfo.CurrentCulture);
        }
    }

    private async void OnConfirmClick(object sender, RoutedEventArgs e)
    {
        if (_busy) return;

        string raw = TxtAmount.Text.Replace(",", "").Trim();
        if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.CurrentCulture, out double amt) || amt <= 0)
        {
            Say("请输入正数金额", Theme.Red);
            return;
        }

        _busy = true;
        SetButtons(false);

        var (ok, err) = await _client.LoanAsync(amt);

        if (!ok)
        {
            _busy = false;
            SetButtons(true);
            Say(string.IsNullOrEmpty(err) ? "借款失败" : err, Theme.Red);
            return;
        }

        // 借款成功：主循环下一拍会发现 negative_remain 消失，由主窗口负责关闭
        Say($"已借入 {amt:N0}", Theme.Green);
        _busy = false;
        _allowClose = true;
        Close();
    }

    private async void OnAbortClick(object sender, RoutedEventArgs e)
    {
        if (_busy) return;

        var r = MessageBox.Show(this,
            "终止本局会立即结算，当前进度全部作废。确定吗？",
            "终止游戏", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
        if (r != MessageBoxResult.Yes) return;

        _busy = true;
        SetButtons(false);
        var (ok, err) = await _client.QuitAsync();

        _busy = false;
        if (!ok)
        {
            SetButtons(true);
            Say(string.IsNullOrEmpty(err) ? "结算失败" : err, Theme.Red);
            return;
        }

        _allowClose = true;
        Close();
    }

    /// <summary>由主窗口在「资金恢复为正」时调用。</summary>
    public void ForceClose()
    {
        _allowClose = true;
        Close();
    }

    private void SetButtons(bool enabled)
    {
        BtnConfirm.IsEnabled = enabled;
        BtnAbort.IsEnabled = enabled;
    }

    private void Say(string text, Brush color)
    {
        TxtMsg.Text = text;
        TxtMsg.Foreground = color;
    }
}
