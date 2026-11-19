using System.Threading;
using System.Windows;
using TokensWatch.Helpers;

namespace TokensWatch;

public partial class App : Application
{
    private Mutex? _mutex;
    private bool _ownsMutex;
    private int _fatalShown;   // 0 = not shown yet; Interlocked guarantees a single dialog

    protected override void OnStartup(StartupEventArgs e)
    {
        // Deliberately a different name from the port lock the Python edition uses (8735):
        // both spectators may run at once so data and feel can be compared item by item.
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
            // The spectator is a read-only window: an unhandled exception must never let the process vanish silently,
            // otherwise the player assumes the game crashed.
            MessageBox.Show(
                "The spectator hit an unhandled error:\n\n" + ErrorText.Describe(args.Exception),
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
            // Do not manufacture new exceptions on the exit path
        }

        _mutex?.Dispose();
        base.OnExit(e);
    }
}
