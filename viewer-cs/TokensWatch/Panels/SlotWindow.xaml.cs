using System.Globalization;
using System.Windows;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 老虎机。对应 tm_watch_ai.py 人类版第 1697-1763 行。
///
/// 前置条件（未满足时主窗口会直接拦下，不打开本窗口）：
///  - 本局开启了【老虎机】（special.slot == true）
///  - 还有剩余次数（slot_left &gt; 0）
/// 单次投入 1~200000，且不超过现金余额。
/// </summary>
public partial class SlotWindow : Window
{
    private readonly StateClient _client;
    private WatchState _state;

    public SlotWindow(StateClient client, WatchState state)
    {
        InitializeComponent();
        _client = client;
        _state = state;

        SourceInitialized += (_, _) => WindowChrome.Apply(this);

        UpdateState(state);

        Loaded += (_, _) =>
        {
            TxtAmount.Focus();
            TxtAmount.SelectAll();
        };
    }

    public void UpdateState(WatchState state)
    {
        _state = state;
        int left = state.Special?.SlotLeft ?? 0;
        TxtSubtitle.Text = $"剩余 {left} 次 · 现金余额 {state.Balance:N0}";
    }

    private async void OnPlayClick(object sender, RoutedEventArgs e)
    {
        string raw = TxtAmount.Text.Replace(",", "").Trim();
        if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.CurrentCulture, out double amt))
        {
            Say("请输入数字", Theme.Red);
            return;
        }

        if (!double.IsFinite(amt) || amt < 1 || amt > 200_000)
        {
            Say("金额必须在 1 ~ 200,000 之间", Theme.Red);
            return;
        }

        if (amt > _state.Balance)
        {
            Say("投入不能超过现金余额", Theme.Red);
            return;
        }

        BtnPlay.IsEnabled = false;

        SlotResult r;
        try
        {
            r = await _client.SlotAsync(amt);
        }
        catch (Exception ex)
        {
            BtnPlay.IsEnabled = true;
            Say("请求失败：" + ex.Message, Theme.Red);
            return;
        }

        BtnPlay.IsEnabled = true;

        if (!r.Ok)
        {
            Say(string.IsNullOrEmpty(r.Error) ? "请求失败" : r.Error, Theme.Red);
            return;
        }

        if (r.Mult > 0)
        {
            Say($"中奖！{r.Mult} 倍，返还 {r.Payout:N0} Tokens。\n" +
                $"目标上浮 {r.BumpPct:+0.00;-0.00;0.00}%（{r.Bump:+#,0;-#,0;0}）", Theme.Green);
        }
        else
        {
            Say("无所得。", Theme.Muted);
        }
    }

    private void OnCancelClick(object sender, RoutedEventArgs e) => Close();

    private void Say(string text, Brush color)
    {
        ResultBox.Visibility = Visibility.Visible;
        TxtResult.Text = text;
        TxtResult.Foreground = color;
    }
}
