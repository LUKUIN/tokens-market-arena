using System.Threading;
using System.Windows;

namespace TokensWatch;

public partial class App : Application
{
    private Mutex? _mutex;
    private bool _ownsMutex;
    private int _fatalShown;   // 0=还没弹过；用 Interlocked 保证只弹一次

    protected override void OnStartup(StartupEventArgs e)
    {
        // 与 Python 版占用的 8735 端口锁**故意不同名**：
        // 两个观众席允许同时开着，方便逐项对比数据与观感。
        _mutex = new Mutex(initiallyOwned: true, name: @"Global\TokensWatchViewerCs", out bool created);
        _ownsMutex = created;

        if (!created)
        {
            MessageBox.Show(
                "已经有一个 Tokens 观众席（C# 版）在运行。",
                "Tokens 观众席",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            Shutdown(0);
            return;
        }

        DispatcherUnhandledException += (_, args) =>
        {
            // 观众席是只读窗口：未处理异常要让玩家看见原因，但不能变成弹窗风暴。
            // 轮询间隔只有几百毫秒，把异常标记为已处理再继续跑，下一次 Tick 会抛出
            // 同类异常并立刻再弹一个**模态**框，用户关不完，界面事实上已经卡死。
            // 所以：弹一次，然后退出，让玩家看到的是明确失败而不是假死。
            if (Interlocked.Exchange(ref _fatalShown, 1) == 1)
            {
                args.Handled = true;
                return;
            }
            MessageBox.Show(
                "观众席遇到未处理的错误，即将退出：\n\n" + args.Exception.Message,
                "Tokens 观众席",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            args.Handled = true;
            Shutdown(1);
        };

        base.OnStartup(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        try
        {
            if (_ownsMutex) _mutex?.ReleaseMutex();
        }
        catch
        {
            // 退出路径上不再制造新异常
        }

        _mutex?.Dispose();
        base.OnExit(e);
    }
}
