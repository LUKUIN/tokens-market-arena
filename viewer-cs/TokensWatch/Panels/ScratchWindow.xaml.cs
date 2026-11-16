using System.Globalization;
using System.Text;
using System.Windows;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 「AI Actions」（Scratchpad）。对应 tm_watch_ai.py 第 732-769 行。
///
/// 一个容易漏掉的细节：Python 侧 `yview_moveto(0.0)` 调了两次（第 768 行立即，
/// 第 769 行 after(80) 再来一次）。WPF 里等价的做法是在 Loaded 之后
/// 用 Dispatcher.BeginInvoke(DispatcherPriority.Loaded) 再滚一次，
/// 否则布局尚未完成，第一次 ScrollToHome 会失效。
/// </summary>
public partial class ScratchWindow : Window
{
    private readonly StateClient _client;

    public ScratchWindow(StateClient client)
    {
        InitializeComponent();
        _client = client;
        Loaded += async (_, _) => await ReloadAsync();
    }

    private async Task ReloadAsync()
    {
        ScratchpadResponse? r;
        try
        {
            r = await _client.GetScratchpadAsync();
        }
        catch (Exception ex)
        {
            TxtTitle.Text = "Scratchpad (读取失败）";
            ContentBox.Text = "Load failed: " + ex.Message;
            return;
        }

        var items = r?.Items ?? new List<ScratchpadItem>();
        TxtTitle.Text = $"Scratchpad ({items.Count} )";

        if (items.Count == 0)
        {
            ContentBox.Text = "The AI hasn't written anything to the scratchpad yet.";
            ContentBox.Foreground = Theme.Muted;
            return;
        }

        ContentBox.Foreground = Theme.Ink;
        var sb = new StringBuilder(items.Count * 120);

        foreach (var x in items)
        {
            string tick = x.Tick.Text;
            string elapsed = x.Elapsed.ToString("0", CultureInfo.CurrentCulture);
            sb.Append('[').Append('t').Append(tick)
              .Append(" · ").Append(elapsed).Append(" 秒]")
              .Append('\n')
              .Append(x.Text ?? "")
              .Append('\n').Append('\n');
        }

        ContentBox.Text = sb.ToString();

        // 两次滚动：与 Python 的第 768/769 行对应
        ContentBox.ScrollToHome();
        await Dispatcher.BeginInvoke(new Action(() => ContentBox.ScrollToHome()),
                                     System.Windows.Threading.DispatcherPriority.Loaded);
    }
}
