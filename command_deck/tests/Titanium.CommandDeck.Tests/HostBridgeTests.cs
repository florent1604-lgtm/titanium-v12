using System.Text;
using Titanium.CommandDeck.Services;

namespace Titanium.CommandDeck.Tests;

[TestClass]
public sealed class HostBridgeTests
{
    private static readonly Uri UiOrigin = new("http://127.0.0.1:8770/ui/");

    [TestMethod]
    public async Task RejectsUnknownIntent()
    {
        var bridge = new CollabHostBridge(new RecordingConfirmation(true));

        await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
            bridge.HandleAsync(new HostIntent("registry.write.raw", "{}"), default));
    }

    [TestMethod]
    [DataRow("chat.publish", "{\"content\":\"Bonjour\"}")]
    [DataRow("task.create", "{\"title\":\"Revoir\",\"owner\":\"codex\",\"priority\":\"P1\"}")]
    [DataRow("task.retry.request", "{\"task_id\":\"task-1\"}")]
    [DataRow("action.preview", "{\"action\":\"open_workspace\",\"parameters\":{}}")]
    [DataRow("host.open_vscode", "{\"path\":\"C:\\\\Users\\\\flore\\\\Desktop\\\\v12\"}")]
    public async Task AcceptsOnlyTheFiveClosedIntentContracts(string type, string payload)
    {
        var confirmation = new RecordingConfirmation(true);
        var bridge = new CollabHostBridge(confirmation);

        var result = await bridge.HandleAsync(new HostIntent(type, payload), default);

        Assert.IsTrue(result.Confirmed);
        Assert.AreEqual("CONFIRMED_PENDING_BROKER", result.ReasonCode);
        Assert.AreEqual(1, confirmation.Calls);
    }

    [TestMethod]
    public async Task RejectsUnknownPayloadFieldsBeforeNativeConfirmation()
    {
        var confirmation = new RecordingConfirmation(true);
        var bridge = new CollabHostBridge(confirmation);

        await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
            bridge.HandleAsync(
                new HostIntent("chat.publish", "{\"content\":\"ok\",\"shell\":\"calc\"}"),
                default));

        Assert.AreEqual(0, confirmation.Calls);
    }

    [TestMethod]
    public async Task RejectsDuplicateNestedJsonFieldsBeforeConfirmation()
    {
        var confirmation = new RecordingConfirmation(true);
        var bridge = new CollabHostBridge(confirmation);

        await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
            bridge.HandleAsync(
                new HostIntent(
                    "action.preview",
                    "{\"action\":\"open_workspace\",\"parameters\":{\"path\":\"a\",\"path\":\"b\"}}"),
                default));

        Assert.AreEqual(0, confirmation.Calls);
    }

    [TestMethod]
    public async Task RejectsMalformedAndOversizeUtf8Messages()
    {
        var bridge = new CollabHostBridge(new RecordingConfirmation(true));
        var multibyteOversize = "{\"type\":\"chat.publish\",\"content\":\"" +
            new string('\u20ac', 22_000) + "\"}";

        await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
            bridge.HandleWebMessageAsync(UiOrigin, "{", default));
        await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
            bridge.HandleWebMessageAsync(UiOrigin, multibyteOversize, default));
        Assert.IsGreaterThan(64 * 1024, Encoding.UTF8.GetByteCount(multibyteOversize));
    }

    [TestMethod]
    public async Task RejectsWebMessagesFromEveryNonExactOrigin()
    {
        var bridge = new CollabHostBridge(new RecordingConfirmation(true));
        const string message = "{\"type\":\"chat.publish\",\"content\":\"ok\"}";

        foreach (var source in new[]
        {
            new Uri("http://localhost:8770/ui/"),
            new Uri("https://127.0.0.1:8770/ui/"),
            new Uri("http://127.0.0.1:8771/ui/"),
            new Uri("http://127.0.0.1.evil.test:8770/ui/")
        })
        {
            await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
                bridge.HandleWebMessageAsync(source, message, default));
        }
    }

    [TestMethod]
    public async Task NativeConfirmationIsFailClosedAndNeverDispatchesAnEffect()
    {
        var bridge = new CollabHostBridge(new RecordingConfirmation(false));

        var result = await bridge.HandleAsync(
            new HostIntent("host.open_vscode", "{}"), default);

        Assert.IsFalse(result.Confirmed);
        Assert.AreEqual("USER_REJECTED", result.ReasonCode);
    }

    [TestMethod]
    public void OriginPolicyAllowsOnlyTheCollabHubOriginAndBoundedWebSocket()
    {
        Assert.IsTrue(OriginPolicy.IsAllowedNavigation(new Uri("http://127.0.0.1:8770/ui/")));
        Assert.IsTrue(OriginPolicy.IsAllowedResource(new Uri("http://127.0.0.1:8770/v1/tasks")));
        Assert.IsTrue(OriginPolicy.IsAllowedResource(new Uri("ws://127.0.0.1:8770/v1/ws")));
        Assert.IsFalse(OriginPolicy.IsAllowedNavigation(new Uri("ws://127.0.0.1:8770/v1/ws")));
        Assert.IsFalse(OriginPolicy.IsAllowedResource(new Uri("ws://127.0.0.1:8770/v1/messages")));
        Assert.IsFalse(OriginPolicy.IsAllowedResource(new Uri("https://127.0.0.1:8770/ui/")));
    }

    [TestMethod]
    public void SessionHeaderIsLimitedToApiAndTheExactWebSocketHandshake()
    {
        Assert.IsTrue(OriginPolicy.RequiresSessionHeader(new Uri("http://127.0.0.1:8770/v1/failures")));
        Assert.IsTrue(OriginPolicy.RequiresSessionHeader(new Uri("ws://127.0.0.1:8770/v1/ws")));
        Assert.IsFalse(OriginPolicy.RequiresSessionHeader(new Uri("http://127.0.0.1:8770/ui/app.mjs")));
        Assert.IsFalse(OriginPolicy.RequiresSessionHeader(new Uri("http://127.0.0.1:8770/health")));
        Assert.IsFalse(OriginPolicy.RequiresSessionHeader(new Uri("http://localhost:8770/v1/tasks")));
    }

    [TestMethod]
    public async Task ConfirmationFailureIsSanitizedAndFailClosed()
    {
        var bridge = new CollabHostBridge(new ThrowingConfirmation());

        var result = await bridge.HandleAsync(
            new HostIntent("chat.publish", "{\"content\":\"ok\"}"), default);

        Assert.IsFalse(result.Confirmed);
        Assert.AreEqual("CONFIRMATION_UNAVAILABLE", result.ReasonCode);
        Assert.DoesNotContain("native dialog raw failure", result.ReasonCode);
    }

    private sealed class RecordingConfirmation(bool answer) : IHostConfirmation
    {
        public int Calls { get; private set; }

        public Task<bool> ConfirmAsync(HostIntent intent, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(answer);
        }
    }

    private sealed class ThrowingConfirmation : IHostConfirmation
    {
        public Task<bool> ConfirmAsync(HostIntent intent, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("native dialog raw failure");
    }
}
