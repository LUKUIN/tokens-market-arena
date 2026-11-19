using System.Windows;
using System.Windows.Media;
using TokensWatch.Helpers;

namespace TokensWatch.Controls;

/// <summary>
/// /// Quote-board sparkline. Mirrors the Python _draw_spark (lines 1268-1284):
/// /// only the last 48 real prices, and nothing at all below 2 points.
/// /// Difference: WPF vector strokes antialias on their own, so 1.4 px never breaks into steps on a diagonal.
/// </summary>
public sealed class Sparkline : FrameworkElement
{
    private IReadOnlyList<double> _points = Array.Empty<double>();
    private Brush _stroke = Theme.Muted;
    private double _strokeWidth = 1.4;

    public Sparkline()
    {
        MinHeight = 20;
        MinWidth = 40;
        RenderOptions.SetEdgeMode(this, EdgeMode.Unspecified);
    }

    public void SetData(IReadOnlyList<double>? history, string colorHex)
    {
        if (history is null || history.Count == 0)
        {
            _points = Array.Empty<double>();
        }
        else
        {
            // // Same as Python: hist[-48:]
            int start = Math.Max(0, history.Count - 48);
            _points = history.Skip(start).ToArray();
        }

        _stroke = Theme.Brush(colorHex);
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext dc)
    {
        double w = ActualWidth;
        double h = ActualHeight;
        if (w <= 2 || h <= 2) return;

        dc.DrawRectangle(Brushes.Transparent, null, new Rect(0, 0, w, h));

        if (_points.Count < 2) return;

        double lo = double.MaxValue, hi = double.MinValue;
        foreach (var v in _points)
        {
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }

        double span = hi - lo;
        if (span <= 0) span = 1.0;

        int n = _points.Count;
        var geo = new StreamGeometry();
        using (var ctx = geo.Open())
        {
            for (int i = 0; i < n; i++)
            {
                double x = 2 + (w - 4) * i / (n - 1);
                double y = h - 3 - (h - 6) * (_points[i] - lo) / span;
                var p = new Point(x, y);
                if (i == 0) ctx.BeginFigure(p, false, false);
                else ctx.LineTo(p, true, true);
            }
        }
        geo.Freeze();

        var pen = new Pen(_stroke, _strokeWidth)
        {
            StartLineCap = PenLineCap.Round,
            EndLineCap = PenLineCap.Round,
            LineJoin = PenLineJoin.Round,
        };
        pen.Freeze();

        dc.DrawGeometry(null, pen, geo);
    }
}
