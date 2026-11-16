using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using TokensWatch.Helpers;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 难度盲盒。对应 tm_watch_ai.py 人类版第 1449-1577 行（_show_roll）。
///
/// 原版是两行实心黑方格「滚动」30 秒（其实方块不变色，只是每 0.1 秒重绘一次），
/// 叫停或归零后点亮中签格并显示档位。这里保留同样的节奏与揭示方式。
/// </summary>
public partial class RollWindow : Window
{
    private static readonly string[] GapNames = { "极低", "低", "中", "高", "极高" };
    private static readonly string[] LiqNames = { "充裕", "正常", "纤薄", "枯竭", "黑洞" };

    private readonly StateClient _client;
    private readonly bool _thenRules;
    private readonly Border[] _gapCells = new Border[5];
    private readonly Border[] _liqCells = new Border[5];

    private DispatcherTimer? _timer;
    private bool _done;
    private bool _allowClose;

    private static readonly Brush BlackCell = MakeBrush("#1A1A1A");
    private static readonly Brush EmptyCell = MakeBrush("#E8E8E8");
    private static readonly Brush PickedCell = MakeBrush("#2D7FF9");

    private static Brush MakeBrush(string hex)
    {
        var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex)!);
        b.Freeze();
        return b;
    }

    public RollWindow(StateClient client, bool thenRules = false)
    {
        InitializeComponent();
        _client = client;
        _thenRules = thenRules;

        SourceInitialized += (_, _) => WindowChrome.Apply(this);

        // 抽选期间不给关：必须叫停或等它走完
        Closing += (_, e) =>
        {
            if (!_allowClose) e.Cancel = true;
        };

        BuildCells();

        Loaded += (_, _) =>
        {
            _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
            _timer.Tick += async (_, _) => await PollTimerAsync();
            _timer.Start();
        };
    }

    private void BuildCells()
    {
        for (int i = 0; i < 5; i++)
        {
            _gapCells[i] = NewCell();
            _liqCells[i] = NewCell();
            GridGap.Children.Add(_gapCells[i]);
            GridLiq.Children.Add(_liqCells[i]);
        }

        foreach (var c in _gapCells) c.Background = BlackCell;
        foreach (var c in _liqCells) c.Background = BlackCell;
    }

    private static Border NewCell() => new()
    {
        Margin = new Thickness(5),
        CornerRadius = new CornerRadius(4),
        Background = BlackCell,
    };

    private async Task PollTimerAsync()
    {
        if (_done) return;

        try
        {
            var st = await _client.GetStateAsync();
            if (st is null) return;

            double left = st.RollLeft ?? 0;
            TxtTimer.Text = $"剩余 {left:0.0} 秒";

            if (left <= 0.001) await StopAsync();
        }
        catch
        {
            // 服务暂时不可达时保持最后一帧，下一拍重试
        }
    }

    private async void OnStopClick(object sender, RoutedEventArgs e) => await StopAsync();

    private async Task StopAsync()
    {
        if (_done) return;
        _done = true;

        _timer?.Stop();
        BtnStop.IsEnabled = false;
        TxtNote.Text = "正在定档…";

        RollResult r;
        try
        {
            r = await _client.RollStopAsync();
        }
        catch (Exception ex)
        {
            TxtNote.Text = "定档失败：" + ex.Message;
            BtnStop.IsEnabled = true;
            BtnStop.Content = "重试";
            _done = false;
            return;
        }

        if (!r.Ok)
        {
            TxtNote.Text = string.IsNullOrEmpty(r.Error) ? "定档失败" : r.Error;
            BtnStop.IsEnabled = true;
            BtnStop.Content = "重试";
            _done = false;
            return;
        }

        Reveal(r);
    }

    private void Reveal(RollResult r)
    {
        int gi = Array.IndexOf(GapNames, r.Gap);
        int li = Array.IndexOf(LiqNames, r.Liq);
        if (gi < 0) gi = 2;
        if (li < 0) li = 2;

        for (int i = 0; i < 5; i++)
        {
            _gapCells[i].Background = i == gi ? PickedCell : EmptyCell;
            _liqCells[i].Background = i == li ? PickedCell : EmptyCell;
        }

        TxtTimer.Text = $"黑天鹅 {r.Gap}   ×   流动性 {r.Liq}";
        TxtNote.Text = "抽选完成，难度已锁定";

        TxtResult.Text = r.GapChance > 0
            ? $"每 tick {r.GapChance * 100:0.00}% 跳空"
            : "";

        BtnStop.Content = _thenRules ? "查看规则" : "开始游戏";
        BtnStop.IsEnabled = true;
        BtnStop.Click -= OnStopClick;
        BtnStop.Click += OnFinishClick;
    }

    private void OnFinishClick(object sender, RoutedEventArgs e)
    {
        _allowClose = true;

        if (_thenRules)
        {
            var rules = new RulesWindow(_client) { Owner = Owner };
            rules.Show();
        }

        Close();
    }
}
