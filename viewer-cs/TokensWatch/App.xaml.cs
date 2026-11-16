using System.Threading;
using System.Windows;

namespace TokensWatch;

public partial class App : Application
{
    private Mutex? _mutex;
    private bool _ownsMutex;

    protected override void OnStartup(StartupEventArgs e)
    {
        // 与 Python 版占用的 8735 端口锁**故意不同名**：
        // 两个观众席允许同时开着，方便逐项对比数据与观感。
        _mutex = new Mutex(initiallyOwned: true, name: @"Global\TokensWatchViewerEn", out bool created);
        _ownsMutex = created;

        if (!created)
        {
            MessageBox.Show(
                "A Tokens spectator (C# build) is already running.",
                "Tokens Spectator",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            Shutdown(0);
            return;
        }

        DispatcherUnhandledException += (_, args) =>
        {
            // 观众席是只读窗口：任何未处理异常都不能让进程静默消失，
            // 否则玩家会以为是游戏崩了。
            MessageBox.Show(
                "The spectator hit an unhandled error:\n\n" + args.Exception.Message,
                "Tokens Spectator",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            args.Handled = true;
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
