using System.Windows;
using System.Windows.Documents;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 「外部的怜悯 · 场外援助」。对应 tm_watch_ai.py 第 625-696 行。
///
/// 语义要点（不能自作主张改动）：
///  - 观众席**不能主动发消息**，只能在参赛者 POST /assist/ask 之后回复或驳回；
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
            TxtSubtitle.Text = "读取失败：" + ex.Message;
            TxtSubtitle.Foreground = Theme.Red;
            return;
        }

        if (a is null)
        {
            TxtSubtitle.Text = "读取失败：空回包";
            TxtSubtitle.Foreground = Theme.Red;
            return;
        }

        // ---------- 副标题 ----------
        if (a.Enabled)
        {
            TxtSubtitle.Text = $"已开通 · 参赛者还可求助 {a.Remaining} 次";
            TxtSubtitle.Foreground = Theme.Muted;
        }
        else
        {
            // v1.2.23 起取消局内付费开通：没开通就是本局没开，不再有补票通道
            TxtSubtitle.Text = "未开通 · 本局不会再有场外援助";
            TxtSubtitle.Foreground = Theme.Orange;
        }

        // ---------- 历史 ----------
        var doc = new FlowDocument { PagePadding = new Thickness(0), FontSize = 12 };

        if (a.Log.Count == 0)
        {
            doc.Blocks.Add(new Paragraph(new Run("本局还没有场外援助记录。"))
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
                    "ai" => ("参赛者", Theme.Blue),
                    "human" => ("观众席", Theme.Brush("#0A7A3D")),
                    _ => ("系统", Theme.Muted),
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
            TxtPendingTitle.Text = $"待处理的求助 {_lastTicket}：";
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
            TxtHint.Text = "内容不能为空";
            TxtHint.Foreground = Theme.Red;
            return;
        }

        if (string.IsNullOrEmpty(_lastTicket))
        {
            TxtHint.Text = "没有待处理的求助";
            TxtHint.Foreground = Theme.Red;
            return;
        }

        SetBusy(true, "发送中…");
        var (ok, err) = await _client.ReplyAsync(_lastTicket, text);
        SetBusy(false, "");

        if (!ok)
        {
            TxtHint.Text = string.IsNullOrEmpty(err) ? "发送失败" : err;
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
            TxtHint.Text = "没有待处理的求助";
            TxtHint.Foreground = Theme.Red;
            return;
        }

        SetBusy(true, "驳回中…");
        var (ok, err) = await _client.RejectAsync(_lastTicket);
        SetBusy(false, "");

        if (!ok)
        {
            TxtHint.Text = string.IsNullOrEmpty(err) ? "驳回失败" : err;
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
