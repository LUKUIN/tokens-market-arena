using System.Globalization;
using System.Windows;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Controls;

/// <summary>
/// /// Equity curve. WPF vector rendering already antialiases, so this only does three things:
/// ///  1. Auto-fit the Y range (the old build pinned -500k to 2.5M, squashing a 0.5% move below one pixel)
/// ///  2. Drop the area fill to 8% opacity (the old build was a solid red wall covering the curve)
/// ///  3. Densify with monotone cubic interpolation (the old build drew sharp polyline corners and could overshoot)
/// /// Reference lines keep "Principal 1M" and "Target": the two hard boundaries of a match.
/// </summary>
public sealed class EquityChart : FrameworkElement
{
    private IReadOnlyList<EquityPoint> _curve = Array.Empty<EquityPoint>();
    private double _baseLine = 1_000_000;
    private double? _targetLine;

    private const double PadLeft = 64;
    private const double PadRight = 16;
    private const double PadTop = 14;
    private const double PadBottom = 32;

    public EquityChart()
    {
        // // Make sure the parent gives enough height, and let WPF render it as vectors
        MinHeight = 120;
        RenderOptions.SetEdgeMode(this, EdgeMode.Unspecified);
        RenderOptions.SetBitmapScalingMode(this, BitmapScalingMode.HighQuality);
    }

    public void SetData(IReadOnlyList<EquityPoint>? curve, double baseLine = 1_000_000, double? target = null)
    {
        _curve = curve ?? Array.Empty<EquityPoint>();
        _baseLine = baseLine;
        _targetLine = target;
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext dc)
    {
        double w = ActualWidth;
        double h = ActualHeight;
        if (w <= 4 || h <= 4) return;

        // // Background
        dc.DrawRectangle(Brushes.Transparent, null, new Rect(0, 0, w, h));

        double plotW = Math.Max(1, w - PadLeft - PadRight);
        double plotH = Math.Max(1, h - PadTop - PadBottom);
        var plotRect = new Rect(PadLeft, PadTop, plotW, plotH);

        if (_curve.Count < 2)
        {
            DrawCentered(dc, plotRect, "No data", Theme.Muted, 13);
            return;
        }

        // // ---------- Y range: auto-fit plus padding, and the Principal line must stay inside ----------
        double dataMin = double.MaxValue;
        double dataMax = double.MinValue;
        foreach (var p in _curve)
        {
            if (p.Equity < dataMin) dataMin = p.Equity;
            if (p.Equity > dataMax) dataMax = p.Equity;
        }

        double lo = Math.Min(dataMin, _baseLine);
        double hi = Math.Max(dataMax, _baseLine);
        if (_targetLine is { } t && t > 0 && t < hi * 1.6) hi = Math.Max(hi, t);

        var (yMin, yMax) = Interpolation.PadRange(lo, hi);
        double ySpan = Math.Max(1e-9, yMax - yMin);

        double XOf(double i) => PadLeft + plotW * (i / Math.Max(1, _curve.Count - 1));
        double YOf(double v) => PadTop + plotH * (1.0 - (v - yMin) / ySpan);

        // // ---------- Grid + Y ticks ----------
        DrawAxis(dc, plotRect, yMin, yMax, YOf);

        // // ---------- X axis: tick marks ----------
        DrawTimeAxis(dc, plotRect);

        // // ---------- Reference lines ----------
        DrawReferenceLine(dc, plotRect, YOf(_baseLine), Theme.Muted, "Principal 1,000,000");
        if (_targetLine is { } tv && tv > 0 && tv <= yMax)
            DrawReferenceLine(dc, plotRect, YOf(tv), Theme.Blue, $"Target {tv:N0}");

        // // ---------- Curve: densify first, then map to screen coordinates ----------
        var raw = new List<Point>(_curve.Count);
        for (int i = 0; i < _curve.Count; i++)
            raw.Add(new Point(XOf(i), _curve[i].Equity));

        // // Fritsch-Carlson shape preservation acts on the value domain, so smooth values here and map Y afterwards
        var smoothVals = Interpolation.MonotoneCubic(
            raw.Select((p, i) => new Point(i, p.Y)).ToList(),
            perSegment: Math.Clamp(220 / Math.Max(1, _curve.Count), 4, 24));

        var screenPts = new List<Point>(smoothVals.Count);
        foreach (var p in smoothVals)
        {
            double xi = PadLeft + plotW * (p.X / Math.Max(1, _curve.Count - 1));
            screenPts.Add(new Point(xi, YOf(p.Y)));
        }

        bool isUp = _curve[^1].Equity >= _curve[0].Equity;
        var lineColor = isUp ? Theme.Green : Theme.Red;

        // // ---------- Gradient fill: 8% at the top, 0 at the bottom ----------
        if (screenPts.Count > 1)
        {
            var areaGeo = new StreamGeometry();
            using (var ctx = areaGeo.Open())
            {
                ctx.BeginFigure(new Point(screenPts[0].X, PadTop + plotH), true, true);
                ctx.LineTo(screenPts[0], false, false);
                foreach (var p in screenPts.Skip(1))
                    ctx.LineTo(p, false, false);
                ctx.LineTo(new Point(screenPts[^1].X, PadTop + plotH), false, false);
            }
            areaGeo.Freeze();

            var fillBrush = new LinearGradientBrush
            {
                StartPoint = new Point(0, 0),
                EndPoint = new Point(0, 1),
                MappingMode = BrushMappingMode.RelativeToBoundingBox,
            };
            var c0 = (Color)ColorConverter.ConvertFromString(Theme.RedHex)!;
            var c1 = (Color)ColorConverter.ConvertFromString(Theme.GreenHex)!;
            var c = isUp ? c1 : c0;
            fillBrush.GradientStops.Add(new GradientStop(Color.FromArgb(20, c.R, c.G, c.B), 0.0));  // ≈8%
            fillBrush.GradientStops.Add(new GradientStop(Color.FromArgb(0, c.R, c.G, c.B), 1.0));
            fillBrush.Freeze();

            dc.DrawGeometry(fillBrush, null, areaGeo);
        }

        // // ---------- The curve itself ----------
        var lineGeo = new StreamGeometry();
        using (var ctx = lineGeo.Open())
        {
            ctx.BeginFigure(screenPts[0], false, false);
            foreach (var p in screenPts.Skip(1))
                ctx.LineTo(p, true, true);
        }
        lineGeo.Freeze();

        var pen = new Pen(lineColor, 2.0)
        {
            StartLineCap = PenLineCap.Round,
            EndLineCap = PenLineCap.Round,
            LineJoin = PenLineJoin.Round,
        };
        pen.Freeze();
        dc.DrawGeometry(null, pen, lineGeo);

        // // ---------- Start / end markers ----------
        DrawDot(dc, screenPts[0], Theme.Muted);
        DrawDot(dc, screenPts[^1], lineColor);

        // ---------- Peak / Trough ----------
        int iMax = 0, iMin = 0;
        for (int i = 1; i < _curve.Count; i++)
        {
            if (_curve[i].Equity > _curve[iMax].Equity) iMax = i;
            if (_curve[i].Equity < _curve[iMin].Equity) iMin = i;
        }

        double peakVal = _curve[iMax].Equity;
        double troughVal = _curve[iMin].Equity;

        var peakPt = new Point(XOf(iMax), YOf(peakVal));
        var troughPt = new Point(XOf(iMin), YOf(troughVal));

        // // Peak label above the point, Trough below it; flip to the other side when the point hugs an edge
        DrawExtremum(dc, peakPt, $"Peak {peakVal:N0}", Theme.GreenHex, preferAbove: true);
        DrawExtremum(dc, troughPt, $"Trough {troughVal:N0}", Theme.RedHex, preferAbove: false);

        // // Final value: tuck it into the top right so it never overlaps the curve
        var last = _curve[^1].Equity;
        DrawText(dc, $"Now {last:N0}", new Point(PadLeft + 6, PadTop + 2), lineColor, 14, bold: true);
    }

    /// /// <summary>Draw a glowing dot at an extreme point and print its value beside it.</summary>
    private void DrawExtremum(DrawingContext dc, Point p, string label, string colorHex, bool preferAbove)
    {
        var color = (Color)ColorConverter.ConvertFromString(colorHex)!;

        var halo = new SolidColorBrush(Color.FromArgb(46, color.R, color.G, color.B));
        halo.Freeze();
        var core = new SolidColorBrush(color);
        core.Freeze();

        dc.DrawEllipse(halo, null, p, 7.5, 7.5);
        dc.DrawEllipse(core, null, p, 3.4, 3.4);

        var ft = MakeText(label, core, 11.5, bold: true);

        // // Above the point by default; flip below when there is no room
        bool above = preferAbove;
        if (above && p.Y - ft.Height - 10 < 2) above = false;
        if (!above && p.Y + ft.Height + 12 > ActualHeight - 2) above = true;

        double x = p.X - ft.Width / 2;
        double y = above ? p.Y - ft.Height - 9 : p.Y + 9;

        // // Clamp horizontally and vertically to the plot area so nothing is clipped
        x = Math.Clamp(x, PadLeft + 2, Math.Max(PadLeft + 2, ActualWidth - ft.Width - 4));
        y = Math.Clamp(y, 2, Math.Max(2, ActualHeight - ft.Height - 2));

        dc.DrawText(ft, new Point(x, y));
    }

    // // ---------------- Drawing helpers ----------------

    private void DrawAxis(DrawingContext dc, Rect plot, double yMin, double yMax, Func<double, double> yOf)
    {
        // // Target: 4 to 6 horizontal ticks. Pick a "round" step so a label never reads like 1234567.
        double span = yMax - yMin;
        double rawStep = span / 5.0;
        double mag = Math.Pow(10, Math.Floor(Math.Log10(Math.Max(1e-9, rawStep))));
        double norm = rawStep / mag;
        double step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;

        double start = Math.Ceiling(yMin / step) * step;
        string _lastAxisLabel = "";
        var gridPen = new Pen(Theme.Brush("#EFEFEF"), 1.0);
        gridPen.Freeze();

        for (double v = start; v <= yMax + 1e-6; v += step)
        {
            double y = yOf(v);
            if (y < plot.Top - 1 || y > plot.Bottom + 1) continue;

            dc.DrawLine(gridPen, new Point(plot.Left, y), new Point(plot.Right, y));

            // // Kill negative zero: .NET prints "-0" for (-0.0).ToString("0"),
            // // and yMin can be -0.0 after PadRange, or carry a minus sign from rounding when |v| < 0.5.
            double vv = Math.Abs(v) < 0.5 ? 0.0 : v;
            // // Keep 3 significant digits for M/K: with a small step (500, say) both 1,000,000 and 1,000,500
            // // would print "1M" at 2 decimals, leaving several identical labels on the axis.
            string label = Math.Abs(vv) >= 1e6 ? $"{vv / 1e6:0.###}M"
                         : Math.Abs(vv) >= 1e3 ? $"{vv / 1e3:0.###}K"
                         : $"{vv:0}";
            // // When two ticks round to the same label ("1M" three times), skip the later one instead of drawing it.
            if (label == _lastAxisLabel) continue;
            _lastAxisLabel = label;
            DrawText(dc, label, new Point(PadLeft - 8, y - 8), Theme.Muted, 11, alignRight: true);
        }
    }

    /// <summary>
    /// /// Bottom tick marks. The curve used to have a Y axis only, so "when did this profit happen" was unanswerable,
    /// /// and a review could not tell an early hold from a late-innings push.
    /// /// Uses ticks rather than wall-clock time: the server only guarantees tick monotonicity, not one per second.
    /// </summary>
    private void DrawTimeAxis(DrawingContext dc, Rect plot)
    {
        if (_curve.Count < 2) return;

        const int marks = 5;
        var axisPen = new Pen(Theme.Brush("#E1E1E1"), 1.0);
        axisPen.Freeze();

        dc.DrawLine(axisPen, new Point(plot.Left, plot.Bottom), new Point(plot.Right, plot.Bottom));

        for (int k = 0; k < marks; k++)
        {
            double frac = (double)k / (marks - 1);
            int idx = (int)Math.Round(frac * (_curve.Count - 1));
            double x = plot.Left + plot.Width * frac;

            dc.DrawLine(axisPen, new Point(x, plot.Bottom), new Point(x, plot.Bottom + 4));

            var ft = MakeText("t" + _curve[idx].Tick, Theme.Muted, 10.5, bold: false);
            double lx = Math.Clamp(x - ft.Width / 2, plot.Left, Math.Max(plot.Left, plot.Right - ft.Width));
            dc.DrawText(ft, new Point(lx, plot.Bottom + 6));
        }
    }

    private void DrawReferenceLine(DrawingContext dc, Rect plot, double y, Brush brush, string label)
    {
        if (y < plot.Top || y > plot.Bottom) return;

        var pen = new Pen(brush, 1.0)
        {
            DashStyle = new DashStyle(new double[] { 4, 4 }, 0),
            DashCap = PenLineCap.Round,
        };
        pen.Freeze();

        dc.DrawLine(pen, new Point(plot.Left, y), new Point(plot.Right, y));
        DrawText(dc, label, new Point(plot.Right - 4, y - 16), brush, 10, alignRight: true);
    }

    private static void DrawDot(DrawingContext dc, Point p, Brush brush)
    {
        dc.DrawEllipse(brush, null, p, 3.0, 3.0);
    }

    private void DrawCentered(DrawingContext dc, Rect area, string text, Brush brush, double size)
    {
        var ft = MakeText(text, brush, size, bold: false);
        dc.DrawText(ft, new Point(area.Left + (area.Width - ft.Width) / 2,
                                   area.Top + (area.Height - ft.Height) / 2));
    }

    private void DrawText(DrawingContext dc, string text, Point at, Brush brush, double size,
                          bool bold = false, bool alignRight = false)
    {
        var ft = MakeText(text, brush, size, bold);
        double x = alignRight ? at.X - ft.Width : at.X;
        dc.DrawText(ft, new Point(x, at.Y));
    }

    private FormattedText MakeText(string text, Brush brush, double size, bool bold)
    {
        return new FormattedText(
            text,
            CultureInfo.CurrentUICulture,
            FlowDirection.LeftToRight,
            new Typeface(new FontFamily(Theme.UiFont), FontStyles.Normal,
                         bold ? FontWeights.SemiBold : FontWeights.Normal, FontStretches.Normal),
            size,
            brush,
            VisualTreeHelper.GetDpi(this).PixelsPerDip);
    }
}
