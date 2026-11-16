using System.Windows;
using System.Windows.Documents;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 「Outside Mercy · Outside Aid」。对应 tm_watch_ai.py 第 625-696 行。
///
/// 语义要点（不能自作主张改动）：
///  - 观众席**不能主动发消息**，只能在参赛者 POST /assist/ask 之后回复或Dismiss；
///  - 开通入口在参赛者一侧，观众席只显示状态；
///  - 历史按 who 上色：ai=参赛者(蓝)、human=观众席(绿)、其他=系统(灰)。
/// </summary>
public partial class AssistWindow : Window
{
    private readonly StateClient _client;
    private string? _lastTicket;

    public AssistWindow(StateClient client)
    {
        InitializeComponent();
        _client = client;
        Loaded += async (_, _) => await ReloadAsync();
    }

    private async Task ReloadAsync()
    {
        AssistPending? a;
        try
        {
            a = await _client.GetAssistPendingAsync();
        }
        catch (Exception ex)
        {
            TxtSubtitle.Text = "Load failed: " + ex.Message;
            TxtSubtitle.Foreground = Theme.Red;
            return;
        }

        if (a is null)
        {
            TxtSubtitle.Text = "Load failed: empty response";
            TxtSubtitle.Foreground = Theme.Red;
            return;
        }

        // ---------- 副标题 ----------
        if (a.Enabled)
        {
            TxtSubtitle.Text = $"Enabled · the contestant can still ask {a.Remaining} more time(s)";
            TxtSubtitle.Foreground = Theme.Muted;
        }
        else
        {
            // Mid-match enabling was removed in v1.2.23: not enabled means not this match.
            TxtSubtitle.Text = "Not enabled · no assistance will be available this match";
            TxtSubtitle.Foreground = Theme.Orange;
        }

        // ---------- 历史 ----------
        var doc = new FlowDocument { PagePadding = new Thickness(0), FontSize = 12 };

        if (a.Log.Count == 0)
        {
            doc.Blocks.Add(new Paragraph(new Run("No Outside Aid records this match."))
            {
                Foreground = Theme.Muted,
            });
        }
        else
        {
            foreach (var x in a.Log)
            {
                (string tag, Brush color) = x.Who switch
                {
                    "ai" => ("Contestant", Theme.Blue),
                    "human" => ("Spectators", Theme.Brush("#0A7A3D")),
                    _ => ("System", Theme.Muted),
                };

                var p = new Paragraph { Margin = new Thickness(0, 0, 0, 10) };
                p.Inlines.Add(new Run($"[t{x.Tick}] ") { Foreground = Theme.Muted });
                p.Inlines.Add(new Run(tag + "：") { Foreground = color, FontWeight = FontWeights.SemiBold });
                p.Inlines.Add(new Run(x.Text ?? ""));
                doc.Blocks.Add(p);
            }
        }

        History.Document = doc;
        History.ScrollToEnd();

        // ---------- 待处理 ----------
        _lastTicket = a.Pending.Count > 0 ? a.Pending[^1].Ticket : null;

        if (a.Pending.Count > 0 && a.Enabled && !string.IsNullOrEmpty(_lastTicket))
        {
            PendingBox.Visibility = Visibility.Visible;
            TxtPendingTitle.Text = $"Pending requests {_lastTicket}：";
            ReplyBox.Focus();
        }
        else
        {
            PendingBox.Visibility = Visibility.Collapsed;
        }
    }

    private async void OnReplyClick(object sender, RoutedEventArgs e)
    {
        string text = ReplyBox.Text.Trim();
        if (text.Length == 0)
        {
            TxtHint.Text = "Message cannot be empty";
            TxtHint.Foreground = Theme.Red;
            return;
        }

        if (string.IsNullOrEmpty(_lastTicket))
        {
            TxtHint.Text = "No pending requests";
            TxtHint.Foreground = Theme.Red;
            return;
        }

        SetBusy(true, "Sending...");
        var (ok, err) = await _client.ReplyAsync(_lastTicket, text);
        SetBusy(false, "");

        if (!ok)
        {
            TxtHint.Text = string.IsNullOrEmpty(err) ? "Send failed" : err;
            TxtHint.Foreground = Theme.Red;
            return;
        }

        ReplyBox.Text = "";
        await ReloadAsync();
    }

    private async void OnRejectClick(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_lastTicket))
        {
            TxtHint.Text = "No pending requests";
            TxtHint.Foreground = Theme.Red;
            return;
        }

        SetBusy(true, "Dismissing...");
        var (ok, err) = await _client.RejectAsync(_lastTicket);
        SetBusy(false, "");

        if (!ok)
        {
            TxtHint.Text = string.IsNullOrEmpty(err) ? "Dismiss failed" : err;
            TxtHint.Foreground = Theme.Red;
            return;
        }

        await ReloadAsync();
    }

    private void SetBusy(bool busy, string hint)
    {
        BtnReply.IsEnabled = !busy;
        BtnReject.IsEnabled = !busy;
        if (hint.Length > 0)
        {
            TxtHint.Text = hint;
            TxtHint.Foreground = Theme.Muted;
        }
    }
}
