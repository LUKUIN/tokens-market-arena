using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Panels;

/// <summary>
/// Activity「More」。对应 tm_watch_ai.py 第 1126-1228 行。
///
/// 三条必须对齐的语义：
///  1. **筛选是共享状态**：这里切分类，主窗口右栏那条也跟着切（Python 的 _log_filter 是成员变量）。
///  2. 六个页签按 _log_cat 归类，Rules见 EventKind。
///  3. **只有原本就停在底部时才跟随滚动**，否则用户往上翻会被强行拽回来（第 1193-1197 行）。
/// </summary>
public partial class LogWindow : Window
{
    private readonly MainWindow _main;
    private readonly List<GameEvent> _events = new();
    private readonly Dictionary<string, Button> _tabButtons = new();
    private int _lastRenderedCount = -1;

    public LogWindow(MainWindow main)
    {
        InitializeComponent();
        _main = main;
        BuildTabs();
        Render(force: true);
    }

    private string Filter => _main.LogFilter;

    private void BuildTabs()
    {
        TabPanel.Children.Clear();
        _tabButtons.Clear();

        foreach (var (key, label) in Theme.LogTabs)
        {
            var btn = new Button
            {
                Content = label,
                Style = (Style)FindResource("TabButton"),
                Margin = new Thickness(0, 0, 5, 0),
            };

            string captured = key;
            btn.Click += (_, _) => SetFilter(captured);

            _tabButtons[key] = btn;
            TabPanel.Children.Add(btn);
        }

        PaintTabs();
    }

    private void PaintTabs()
    {
        string current = Filter;
        foreach (var (key, btn) in _tabButtons)
        {
            bool on = key == current;
            btn.Background = on ? Theme.Blue : Theme.Brush("#F1F1F1");
            btn.Foreground = on ? Brushes.White : Theme.Muted;
        }
    }

    private void SetFilter(string key)
    {
        if (Filter == key) return;

        // 交给主窗口统一改，主窗口会回调 RenderLogFeed，内外同步
        _main.SetLogFilter(key);
        PaintTabs();
        Render(force: true);
    }

    /// <summary>主窗口拿到新事件后调用（传入去重后的完整列表）。</summary>
    public void AppendAll(IReadOnlyList<GameEvent> events)
    {
        _events.Clear();
        _events.AddRange(events);

        if (_events.Count != _lastRenderedCount)
        {
            PaintTabs();       // 主窗口可能改过筛选
            Render();
        }
    }

    private void Render(bool force = false)
    {
        _lastRenderedCount = _events.Count;

        bool atBottom = IsAtBottom();

        string filter = Filter;
        var rows = filter == "all"
            ? _events
            : _events.Where(e => EventKind.Category(e) == filter).ToList();

        // Only lightweight rows are built here; the virtualizing panel creates the
        // actual TextBlocks on demand, so keeping the full history stays cheap.
        LogList.ItemsSource = rows.Count == 0
            ? new List<LogRow> { new() { Display = "No events.", Brush = Theme.Muted } }
            : rows.Select(e => new LogRow
              {
                  Display = $"[t{e.Tick}] {e.Text}",
                  Brush = Theme.Brush(EventKind.ColorHex(e)),
              }).ToList();

        if ((atBottom || force) && LogList.Items.Count > 0)
            LogList.ScrollIntoView(LogList.Items[LogList.Items.Count - 1]);
    }

    private bool IsAtBottom()
    {
        // ViewportHeight / ExtentHeight are 0 before the first layout pass; treat that as "at bottom".
        var sv = FindScrollViewer(LogList);
        if (sv is null || sv.ExtentHeight <= 0) return true;
        return sv.VerticalOffset + sv.ViewportHeight >= sv.ExtentHeight - 1.5;
    }

    private static ScrollViewer? FindScrollViewer(DependencyObject root)
    {
        int n = VisualTreeHelper.GetChildrenCount(root);
        for (int i = 0; i < n; i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is ScrollViewer sv) return sv;
            var deep = FindScrollViewer(child);
            if (deep is not null) return deep;
        }
        return null;
    }

}

/// <summary>One activity row. The virtualizing panel only instantiates the visible ones;
/// the type must be reachable or WPF's binding reflection cannot read its properties.</summary>
internal sealed class LogRow
{
    public string Display { get; init; } = "";
    public System.Windows.Media.Brush Brush { get; init; } = System.Windows.Media.Brushes.Black;
}
