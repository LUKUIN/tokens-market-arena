using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Panels;

/// <summary>
/// /// Activity "More". Mirrors tm_watch_ai.py lines 1126-1228.
///
/// /// Three semantics that must match:
/// ///  1. The filter is shared state: switching a category here also switches the newest line in the right column (Python keeps _log_filter on the instance).
/// ///  2. Six tabs are classified by _log_cat; the rules live in EventKind.
/// ///  3. Follow-scroll only when already pinned to the bottom, otherwise a user scrolling up gets yanked back (lines 1193-1197).
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

        //         // Hand it to the main window, which calls back RenderLogFeed so inside and outside stay in sync
        _main.SetLogFilter(key);
        PaintTabs();
        Render(force: true);
    }

    ///     /// <summary>Called by the main window when new events arrive (passes the deduplicated full list).</summary>
    public void AppendAll(IReadOnlyList<GameEvent> events)
    {
        _events.Clear();
        _events.AddRange(events);

        if (_events.Count != _lastRenderedCount)
        {
            PaintTabs();       // the main window may have changed the filter
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
