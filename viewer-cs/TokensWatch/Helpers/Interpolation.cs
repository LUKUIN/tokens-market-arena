using System.Windows;

namespace TokensWatch.Helpers;

/// <summary>
/// 单调三次 Hermite 插值（Fritsch–Carlson 限制）。
///
/// 为什么不用现成的平滑算法：
///  - 三次样条（cubic spline）在金融数据上会产生**过冲**，曲线会穿到历史极值之外，
///    看起来比实际波动更夸张，属于造假。
///  - Catmull-Rom 同样不保形。
///  - Fritsch–Carlson 保证：曲线**经过每个原始点**，且**不会越出相邻两点构成的区间**。
///    这正是权益曲线需要的性质。
/// </summary>
public static class Interpolation
{
    /// <summary>
    /// 把折线加密成平滑曲线。输入按 X 升序，X 重复时以最后一个为准。
    /// </summary>
    /// <param name="src">原始点（至少 2 个）</param>
    /// <param name="perSegment">每段插入的采样数，越大越圆滑；10~20 之间足够</param>
    public static List<Point> MonotoneCubic(IReadOnlyList<Point> src, int perSegment = 10)
    {
        if (perSegment < 1) perSegment = 1;
        int n = src.Count;
        if (n < 3)
        {
            // 少于 3 个点没有“曲率”可言，原样返回
            return new List<Point>(src);
        }

        var xs = new double[n];
        var ys = new double[n];
        for (int i = 0; i < n; i++)
        {
            xs[i] = src[i].X;
            ys[i] = src[i].Y;
        }

        // 1) 各区间割线斜率
        var delta = new double[n - 1];
        for (int i = 0; i < n - 1; i++)
        {
            double dx = xs[i + 1] - xs[i];
            delta[i] = Math.Abs(dx) < 1e-12 ? 0.0 : (ys[i + 1] - ys[i]) / dx;
        }

        // 2) 初始切线：内部取相邻割线的平均，两端取端割线
        var m = new double[n];
        m[0] = delta[0];
        m[n - 1] = delta[n - 2];
        for (int i = 1; i < n - 1; i++)
            m[i] = (delta[i - 1] + delta[i]) / 2.0;

        // 3) Fritsch–Carlson 限制：保证不越界
        for (int i = 0; i < n - 1; i++)
        {
            if (Math.Abs(delta[i]) < 1e-12)
            {
                // 平坦区间，两端切线置零，避免出现鼓包
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

        // 4) 逐段 Hermite 求值
        var result = new List<Point>((n - 1) * perSegment + 1);
        result.Add(new Point(xs[0], ys[0]));

        for (int i = 0; i < n - 1; i++)
        {
            double h = xs[i + 1] - xs[i];
            if (h <= 0)
            {
                // X 非递增时退化为直线，绝不除以零
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
    /// 给纵轴留白：按数据范围上下各扩 12%，并避免零跨度（全平局）时除零。
    /// </summary>
    public static (double Min, double Max) PadRange(double dataMin, double dataMax, double padRatio = 0.12)
    {
        double span = dataMax - dataMin;
        if (span <= 1e-9)
        {
            // 完全水平的曲线：给一个固定视觉厚度，否则会贴在边框上
            double pad = Math.Max(Math.Abs(dataMax) * 0.002, 1.0);
            return (dataMin - pad, dataMax + pad);
        }
        double padAmt = span * padRatio;
        return (dataMin - padAmt, dataMax + padAmt);
    }
}
