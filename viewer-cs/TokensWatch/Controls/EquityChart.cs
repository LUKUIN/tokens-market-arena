using System.Globalization;
using System.Windows;
using System.Windows.Media;
using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Controls;

/// <summary>
/// 权益曲线。WPF 矢量渲染自带抗锯齿，因此这里只做三件事：
///  1. 纵轴**自适应**（旧版固定在 -50 万~250 万，把 0.5% 的波动压成亚像素，看不出涨跌）
///  2. 面积填充压到 8% 透明度（旧版糊成一堵红墙，把曲线整个盖住）
///  3. 单调三次插值加密（旧版是折线，拐角处生硬；且不能越界）
/// 参考线保留「本金 100 万」与「目标」，它们是对局的两条硬边界。
/// </summary>
public sealed class EquityChart : FrameworkElement
{
    private IReadOnlyList<EquityPoint> _curve = Array.Empty<EquityPoint>();
    private double _baseLine = 1_000_000;
    private double? _targetLine;

    private const double PadLeft = 64;
    private const double PadRight = 16;
    private const double CurrentLabelBand = 18;
    private const double PadTop = 28;
    private const double PadBottom = 25;

    public EquityChart()
    {
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
        if (w <= PadLeft + PadRight || h <= PadTop + PadBottom) return;

        // 背景
        dc.DrawRectangle(Brushes.Transparent, null, new Rect(0, 0, w, h));

        double plotW = Math.Max(1, w - PadLeft - PadRight);
        double plotH = Math.Max(1, h - PadTop - PadBottom);
        var plotRect = new Rect(PadLeft, PadTop, plotW, plotH);

        if (_curve.Count < 2)
        {
            DrawCentered(dc, plotRect, "暂无数据", Theme.Muted, 13);
            return;
        }

        // ---------- 纵轴范围：自适应 + 留白，且必须把本金线包进去 ----------
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

        // ---------- 网格 + Y 轴刻度 ----------
        DrawAxis(dc, plotRect, yMin, yMax, YOf);

        // ---------- X 轴：tick 刻度 ----------
        DrawTimeAxis(dc, plotRect);

        // ---------- 参考线 ----------
        DrawReferenceLine(dc, plotRect, YOf(_baseLine), Theme.Muted, "本金 1,000,000");
        if (_targetLine is { } tv && tv > 0 && tv <= yMax)
            DrawReferenceLine(dc, plotRect, YOf(tv), Theme.Blue, $"目标 {tv:N0}");

        // ---------- 曲线：先加密，再统一映射到屏幕坐标 ----------
        var raw = new List<Point>(_curve.Count);
        for (int i = 0; i < _curve.Count; i++)
            raw.Add(new Point(XOf(i), _curve[i].Equity));

        // Fritsch–Carlson 的保形性作用在「值域」上，所以在这里先平滑值、再映射 Y
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

        // ---------- 渐变填充：顶部 8% → 底部 0 ----------
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

        // ---------- 曲线本体 ----------
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

        // ---------- 起终点标记 ----------
        DrawDot(dc, screenPts[0], Theme.Muted);
        DrawDot(dc, screenPts[^1], lineColor);

        // ---------- 峰值 / 谷值 ----------
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

        // 峰值在点上方、谷值在点下方；贴边时自动翻到另一侧
        DrawExtremum(dc, peakPt, $"峰 {peakVal:N0}", Theme.GreenHex, preferAbove: true);
        if (iMin != iMax)
            DrawExtremum(dc, troughPt, $"谷 {troughVal:N0}", Theme.RedHex, preferAbove: false);

        var last = _curve[^1].Equity;
        DrawText(dc, $"当前 {last:N0}", new Point(PadLeft + 6, 1), lineColor, 14, bold: true);
    }

    /// <summary>在极值点画一个带光晕的圆点，并在旁边标出数值。</summary>
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

        // 默认在点上方；上方放不开就翻到下方
        bool above = preferAbove;
        if (above && p.Y - ft.Height - 10 < CurrentLabelBand) above = false;
        double chartBottom = ActualHeight - PadBottom;
        if (!above && p.Y + ft.Height + 12 > chartBottom) above = true;

        double x = p.X - ft.Width / 2;
        double y = above ? p.Y - ft.Height - 9 : p.Y + 9;

        // 左右/上下夹到绘图区内，避免被裁掉
        x = Math.Clamp(x, PadLeft + 2, Math.Max(PadLeft + 2, ActualWidth - ft.Width - 4));
        y = Math.Clamp(y, CurrentLabelBand, Math.Max(CurrentLabelBand, chartBottom - ft.Height - 2));

        dc.DrawText(ft, new Point(x, y));
    }

    // ---------------- 绘制辅助 ----------------

    private void DrawAxis(DrawingContext dc, Rect plot, double yMin, double yMax, Func<double, double> yOf)
    {
        // 目标：4~6 条水平刻度。取一个“整”步长，别让标签变成 1234567 这种。
        double span = yMax - yMin;
        double rawStep = span / 5.0;
        double mag = Math.Pow(10, Math.Floor(Math.Log10(Math.Max(1e-9, rawStep))));
        double norm = rawStep / mag;
        double step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;

        double start = Math.Ceiling(yMin / step) * step;
        var gridPen = new Pen(Theme.Brush("#EFEFEF"), 1.0);
        gridPen.Freeze();

        for (double v = start; v <= yMax + 1e-6; v += step)
        {
            double y = yOf(v);
            if (y < plot.Top - 1 || y > plot.Bottom + 1) continue;

            dc.DrawLine(gridPen, new Point(plot.Left, y), new Point(plot.Right, y));

            string label = Math.Abs(v) >= 1e6 ? $"{v / 1e6:0.##}M"
                         : Math.Abs(v) >= 1e3 ? $"{v / 1e3:0.#}K"
                         : $"{v:0}";
            DrawText(dc, label, new Point(PadLeft - 8, y - 8), Theme.Muted, 11, alignRight: true);
        }
    }

    /// <summary>
    /// 底部 tick 刻度。曲线原来只有 Y 轴，看不出「这段盈利发生在什么时候」，
    /// 复盘时无法判断某一段是早期扛出来的还是尾盘冲的。
    /// 用 tick 而不是墙钟时间：服务端只保证 tick 单调，不保证每秒一个。
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
