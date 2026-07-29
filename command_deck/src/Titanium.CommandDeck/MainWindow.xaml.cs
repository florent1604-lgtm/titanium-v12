using System.IO;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using Microsoft.Web.WebView2.Core;
using Titanium.CommandDeck.Services;

namespace Titanium.CommandDeck;

public partial class MainWindow : Window, IHostConfirmation
{
    private readonly CancellationTokenSource _lifetime = new();
    private readonly CollabSessionClient _session;
    private readonly CollabHostBridge _bridge;

    public MainWindow()
    {
        InitializeComponent();
        var identity = new WindowsIdentityService();
        var expectedSid = identity.CurrentSid;
        _session = new CollabSessionClient(
            new HttpClient
            {
                BaseAddress = new Uri("http://127.0.0.1:8770/"),
                Timeout = TimeSpan.FromSeconds(5)
            },
            identity,
            new DpapiBootstrapKeyStore(),
            expectedSid);
        _bridge = new CollabHostBridge(this);
        Loaded += OnLoaded;
        Closed += OnClosed;
    }

    public Task<bool> ConfirmAsync(HostIntent intent, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var answer = MessageBox.Show(
            this,
            $"Confirmer la demande « {intent.Type} » ?\n\n" +
            "Aucun effet Windows ou trading ne sera exécuté directement par cette coque.",
            "Validation Florent",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question,
            MessageBoxResult.No);
        return Task.FromResult(answer == MessageBoxResult.Yes);
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            await InitializeWebViewAsync(_lifetime.Token);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
        }
        catch (Exception)
        {
            ShowStatus("Command Deck indisponible — vérifiez CollabHub et la session Windows.");
        }
    }

    private async Task InitializeWebViewAsync(CancellationToken cancellationToken)
    {
        var sessionReady = false;
        try
        {
            await _session.OpenAsync(cancellationToken);
            sessionReady = true;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            ShowStatus("Session Windows indisponible — ouverture en lecture limitée.");
        }

        var profilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Titanium",
            "CommandDeck",
            "WebView2");
        Directory.CreateDirectory(profilePath);
        var environment = await CoreWebView2Environment.CreateAsync(
            browserExecutableFolder: null,
            userDataFolder: profilePath);
        cancellationToken.ThrowIfCancellationRequested();
        await DeckWebView.EnsureCoreWebView2Async(environment);
        ConfigureWebView();
        DeckWebView.Source = OriginPolicy.UiUri;
        if (sessionReady)
        {
            StatusOverlay.Visibility = Visibility.Collapsed;
        }
    }

    private void ConfigureWebView()
    {
        var core = DeckWebView.CoreWebView2;
        core.Settings.AreHostObjectsAllowed = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.IsBuiltInErrorPageEnabled = false;
#if !DEBUG
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = false;
#endif
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        core.NavigationStarting += OnNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.WebResourceRequested += OnWebResourceRequested;
        core.WebMessageReceived += OnWebMessageReceived;
        core.PermissionRequested += OnPermissionRequested;
        core.DownloadStarting += OnDownloadStarting;
        core.ProcessFailed += OnProcessFailed;
    }

    private static void OnNavigationStarting(
        object? sender,
        CoreWebView2NavigationStartingEventArgs e)
    {
        if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri) ||
            !OriginPolicy.IsAllowedNavigation(uri))
        {
            e.Cancel = true;
        }
    }

    private static void OnNewWindowRequested(
        object? sender,
        CoreWebView2NewWindowRequestedEventArgs e)
    {
        e.Handled = true;
    }

    private void OnWebResourceRequested(
        object? sender,
        CoreWebView2WebResourceRequestedEventArgs e)
    {
        var core = DeckWebView.CoreWebView2;
        if (!Uri.TryCreate(e.Request.Uri, UriKind.Absolute, out var uri) ||
            !OriginPolicy.IsAllowedResource(uri))
        {
            e.Response = DeniedResponse(core.Environment, HttpStatusCode.Forbidden, "Forbidden");
            return;
        }
        if (!OriginPolicy.RequiresSessionHeader(uri))
        {
            return;
        }
        try
        {
            _session.UseSessionToken(token =>
                e.Request.Headers.SetHeader("X-Collab-Session", token));
        }
        catch (Exception)
        {
            e.Response = DeniedResponse(core.Environment, HttpStatusCode.Unauthorized, "Unauthorized");
        }
    }

    private async void OnWebMessageReceived(
        object? sender,
        CoreWebView2WebMessageReceivedEventArgs e)
    {
        HostIntentResult result;
        try
        {
            if (!Uri.TryCreate(e.Source, UriKind.Absolute, out var source))
            {
                throw new InvalidOperationException("WEB_MESSAGE_ORIGIN_REJECTED");
            }
            result = await _bridge.HandleWebMessageAsync(
                source,
                e.WebMessageAsJson,
                _lifetime.Token);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            return;
        }
        catch (Exception)
        {
            result = new HostIntentResult(false, "HOST_INTENT_REJECTED");
        }

        if (DeckWebView.CoreWebView2 is not null)
        {
            DeckWebView.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(new
            {
                type = "host.intent.result",
                confirmed = result.Confirmed,
                reason_code = result.ReasonCode
            }));
        }
    }

    private static void OnPermissionRequested(
        object? sender,
        CoreWebView2PermissionRequestedEventArgs e)
    {
        e.State = CoreWebView2PermissionState.Deny;
    }

    private static void OnDownloadStarting(
        object? sender,
        CoreWebView2DownloadStartingEventArgs e)
    {
        e.Cancel = true;
    }

    private void OnProcessFailed(object? sender, CoreWebView2ProcessFailedEventArgs e)
    {
        ShowStatus("Moteur d’interface interrompu — redémarrage manuel requis.");
    }

    private static CoreWebView2WebResourceResponse DeniedResponse(
        CoreWebView2Environment environment,
        HttpStatusCode status,
        string reason) => environment.CreateWebResourceResponse(
            Stream.Null,
            (int)status,
            reason,
            "Content-Type: text/plain; charset=utf-8\r\nCache-Control: no-store");

    private void ShowStatus(string message)
    {
        StatusText.Text = message;
        StatusOverlay.Visibility = Visibility.Visible;
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        _lifetime.Cancel();
        _session.Dispose();
        _lifetime.Dispose();
    }
}
