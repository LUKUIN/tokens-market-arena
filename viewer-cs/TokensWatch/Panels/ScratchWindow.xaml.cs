using System.Globalization;
using System.Text;
using System.Windows;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// /// "AI Actions" (Scratchpad). Mirrors tm_watch_ai.py lines 732-769.
///
/// /// One easy-to-miss detail: Python calls yview_moveto(0.0) twice (line 768 immediately,
/// /// line 769 again after(80)). The WPF equivalent is to scroll once more after Loaded
/// /// through Dispatcher.BeginInvoke(DispatcherPriority.Loaded),
/// /// otherwise layout is not finished and the first ScrollToHome is a no-op.
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
            TxtTitle.Text = "Scratchpad (load failed)";
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
              .Append(" · ").Append(elapsed).Append(" s]")
              .Append('\n')
              .Append(x.Text ?? "")
              .Append('\n').Append('\n');
        }

        ContentBox.Text = sb.ToString();

        //         // Two scrolls: mirrors Python lines 768/769
        ContentBox.ScrollToHome();
        await Dispatcher.BeginInvoke(new Action(() => ContentBox.ScrollToHome()),
                                     System.Windows.Threading.DispatcherPriority.Loaded);
    }
}
