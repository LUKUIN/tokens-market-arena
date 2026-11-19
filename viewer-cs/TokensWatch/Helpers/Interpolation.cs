using System.Windows;

namespace TokensWatch.Helpers;

/// <summary>
/// Monotone cubic Hermite interpolation (Fritsch-Carlson limits).
///
/// Why not an off-the-shelf smoother:
///  - A cubic spline overshoots on financial data: the curve runs past historical extremes,
///    looking more volatile than it really was, which is a form of fabrication.
///  - Catmull-Rom is not shape preserving either.
///  - Fritsch-Carlson guarantees the curve passes through every original point and never leaves
///    the interval spanned by two adjacent points, which is exactly what an equity curve needs.
/// </summary>
public static class Interpolation
{
    /// <summary>
    ///     /// Densify a polyline into a smooth curve. Input must ascend in X; on duplicate X the last one wins.
    /// </summary>
    ///     /// <param name="src">Original points (at least 2)</param>
    ///     /// <param name="perSegment">Samples inserted per segment; larger is smoother, 10-20 is plenty</param>
    public static List<Point> MonotoneCubic(IReadOnlyList<Point> src, int perSegment = 10)
    {
        if (perSegment < 1) perSegment = 1;
        int n = src.Count;
        if (n < 3)
        {
            //             // Fewer than 3 points have no "curvature"; return them unchanged
            return new List<Point>(src);
        }

        var xs = new double[n];
        var ys = new double[n];
        for (int i = 0; i < n; i++)
        {
            xs[i] = src[i].X;
            ys[i] = src[i].Y;
        }

        //         // 1) Secant slope of each interval
        var delta = new double[n - 1];
        for (int i = 0; i < n - 1; i++)
        {
            double dx = xs[i + 1] - xs[i];
            delta[i] = Math.Abs(dx) < 1e-12 ? 0.0 : (ys[i + 1] - ys[i]) / dx;
        }

        //         // 2) Initial tangents: average of adjacent secants inside, the end secant at the edges
        var m = new double[n];
        m[0] = delta[0];
        m[n - 1] = delta[n - 2];
        for (int i = 1; i < n - 1; i++)
            m[i] = (delta[i - 1] + delta[i]) / 2.0;

        //         // 3) Fritsch-Carlson limiter: keeps the curve inside the data
        for (int i = 0; i < n - 1; i++)
        {
            if (Math.Abs(delta[i]) < 1e-12)
            {
                //                 // Flat interval: zero both tangents so no bump appears
                m[i] = 0.0;
                m[i + 1] = 0.0;
                continue;
            }

            double a = m[i] / delta[i];
            double b = m[i + 1] / delta[i];
            double s = a * a + b * b;

            if (s > 9.0)
            {
                double tau = 3.0 / Math.Sqrt(s);
                m[i] = tau * a * delta[i];
                m[i + 1] = tau * b * delta[i];
            }
        }

        //         // 4) Evaluate Hermite per segment
        var result = new List<Point>((n - 1) * perSegment + 1);
        result.Add(new Point(xs[0], ys[0]));

        for (int i = 0; i < n - 1; i++)
        {
            double h = xs[i + 1] - xs[i];
            if (h <= 0)
            {
                //                 // Non-increasing X degenerates to a straight line; never divide by zero
                result.Add(new Point(xs[i + 1], ys[i + 1]));
                continue;
            }

            for (int k = 1; k <= perSegment; k++)
            {
                double t = (double)k / perSegment;
                double t2 = t * t;
                double t3 = t2 * t;

                double h00 = 2 * t3 - 3 * t2 + 1;
                double h10 = t3 - 2 * t2 + t;
                double h01 = -2 * t3 + 3 * t2;
                double h11 = t3 - t2;

                double v = h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1];
                result.Add(new Point(xs[i] + h * t, v));
            }
        }

        return result;
    }

    /// <summary>
    ///     /// Pad the Y axis: extend the data range by 12% on both sides and avoid division by zero on a flat match.
    /// </summary>
    public static (double Min, double Max) PadRange(double dataMin, double dataMax, double padRatio = 0.12)
    {
        double span = dataMax - dataMin;
        if (span <= 1e-9)
        {
            //             // Perfectly flat curve: give it a fixed visual thickness, otherwise it sits on the border
            double pad = Math.Max(Math.Abs(dataMax) * 0.002, 1.0);
            return (dataMin - pad, dataMax + pad);
        }
        double padAmt = span * padRatio;
        return (dataMin - padAmt, dataMax + padAmt);
    }
}
