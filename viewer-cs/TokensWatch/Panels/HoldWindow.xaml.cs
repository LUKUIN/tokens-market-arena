using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Panels;

/// <summary>
/// Positions「More」。对应 tm_watch_ai.py 第 1230-1266 行。
/// 弹窗内容跟随主循环刷新，关闭后由主窗口清引用。
/// </summary>
public partial class HoldWindow : Window
{
    public HoldWindow()
    {
        InitializeComponent();
    }

    public void UpdateRows(IReadOnlyList<Position> positions)
    {
        Rows.Children.Clear();

        if (positions.Count == 0)
        {
            Rows.Children.Add(new TextBlock
            {
                Text = "No open positions",
                FontSize = 12,
                Foreground = Theme.Muted,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 24, 0, 24),
            });
            return;
        }

        foreach (var p in positions)
        {
            var row = new UniformGrid { Columns = 8, Margin = new Thickness(0, 4, 0, 4) };

            row.Children.Add(Cell(p.Pair, Theme.Brush(Theme.PairColor(p.Pair)), left: true));
            row.Children.Add(Cell(p.Side == "LONG" ? "多" : "空",
                                  p.Side == "LONG" ? Theme.Green : Theme.Red));
            row.Children.Add(Cell(p.Lots.ToString("0.##", CultureInfo.CurrentCulture)));
            row.Children.Add(Cell(p.Leverage.ToString("0", CultureInfo.CurrentCulture) + "x"));
            row.Children.Add(Cell(p.Entry.ToString("0.##", CultureInfo.CurrentCulture), mono: true));
            row.Children.Add(Cell(p.Price.ToString("0.##", CultureInfo.CurrentCulture), mono: true));
            row.Children.Add(Cell(p.Margin.ToString("N0", CultureInfo.CurrentCulture), mono: true));
            row.Children.Add(Cell(p.Upnl.ToString("+#,0;-#,0;0", CultureInfo.CurrentCulture),
                                  p.Upnl >= 0 ? Theme.Green : Theme.Red, mono: true));

            Rows.Children.Add(row);
        }
    }

    private static TextBlock Cell(string text, Brush? brush = null, bool mono = false, bool left = false)
    {
        var tb = new TextBlock
        {
            Text = text,
            FontSize = 13,
            FontFamily = new FontFamily(mono ? Theme.MonoFont : Theme.UiFont),
            HorizontalAlignment = left ? HorizontalAlignment.Left : HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = brush ?? Theme.Ink,
            TextTrimming = TextTrimming.CharacterEllipsis,
        };
        if (left) tb.Margin = new Thickness(4, 0, 0, 0);
        return tb;
    }
}
