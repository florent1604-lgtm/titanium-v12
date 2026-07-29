using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Titanium.CommandDeck.Services;

namespace Titanium.CommandDeck.Tests;

[TestClass]
public sealed class CollabSessionClientTests
{
    private const string Sid = "S-1-5-21-florent";
    private static readonly DateTimeOffset Now = new(2026, 7, 22, 8, 0, 0, TimeSpan.Zero);
    private static readonly byte[] Key = Enumerable.Range(1, 32).Select(value => (byte)value).ToArray();

    [TestMethod]
    public async Task OpenAsyncUsesTheExactSidNonceAndCanonicalExpirationHmac()
    {
        const string nonce = "nonce-unique";
        const string challengeExpiry = "2026-07-22T08:00:30+00:00";
        var handler = new ScriptedHandler(request =>
        {
            if (request.RequestUri!.AbsolutePath == "/v1/session/challenge")
            {
                Assert.AreEqual(HttpMethod.Post, request.Method);
                return Json(HttpStatusCode.Created,
                    JsonSerializer.Serialize(new { nonce, expires_at = challengeExpiry }));
            }

            Assert.AreEqual("/v1/session/windows", request.RequestUri.AbsolutePath);
            using var body = JsonDocument.Parse(request.Content!.ReadAsStringAsync().GetAwaiter().GetResult());
            var root = body.RootElement;
            Assert.AreEqual(Sid, root.GetProperty("sid").GetString());
            Assert.AreEqual(nonce, root.GetProperty("nonce").GetString());
            var expected = Convert.ToHexString(HMACSHA256.HashData(
                    Key,
                    Encoding.UTF8.GetBytes($"{Sid}|{nonce}|{challengeExpiry}")))
                .ToLowerInvariant();
            Assert.AreEqual(expected, root.GetProperty("proof").GetString());
            return Json(HttpStatusCode.Created,
                "{\"token\":\"memory-only-token-1234\",\"session_id\":\"session-1\",\"expires_at\":\"2026-07-22T08:15:00+00:00\"}");
        });
        var keyStore = new RecordingKeyStore(Key);
        using var client = CreateClient(handler, keyStore);

        await client.OpenAsync(default);

        Assert.IsTrue(client.IsOpen);
        Assert.AreEqual(new DateTimeOffset(2026, 7, 22, 8, 15, 0, TimeSpan.Zero), client.ExpiresAt);
        Assert.IsTrue(keyStore.LastReturned!.All(value => value == 0));
        Assert.AreEqual(2, handler.Calls);
    }

    [TestMethod]
    public async Task RefusesUnexpectedWindowsSidBeforeReadingAKeyOrCallingHttp()
    {
        var handler = new ScriptedHandler(_ => throw new AssertFailedException("HTTP must not be called"));
        var keyStore = new RecordingKeyStore(Key);
        using var client = CreateClient(handler, keyStore, currentSid: "S-1-5-21-other");

        await Assert.ThrowsExactlyAsync<InvalidOperationException>(() => client.OpenAsync(default));

        Assert.AreEqual(0, handler.Calls);
        Assert.AreEqual(0, keyStore.Calls);
    }

    [TestMethod]
    public async Task RefusesExpiredOrNonUtcChallengeMetadata()
    {
        foreach (var expiresAt in new[]
        {
            "2026-07-22T07:59:59+00:00",
            "2026-07-22T10:00:30+02:00",
            "2026-07-22 08:00:30Z"
        })
        {
            var handler = new ScriptedHandler(_ => Json(HttpStatusCode.Created,
                JsonSerializer.Serialize(new { nonce = "nonce", expires_at = expiresAt })));
            using var client = CreateClient(handler, new RecordingKeyStore(Key));

            await Assert.ThrowsExactlyAsync<InvalidOperationException>(() => client.OpenAsync(default));
            Assert.AreEqual(1, handler.Calls);
        }
    }

    [TestMethod]
    public async Task RefusesUnexpectedStatusMalformedSchemaAndOversizeBodies()
    {
        var cases = new Func<HttpResponseMessage>[]
        {
            () => Json(HttpStatusCode.OK, "{\"nonce\":\"n\",\"expires_at\":\"2026-07-22T08:00:30+00:00\"}"),
            () => Json(HttpStatusCode.Created, "{\"nonce\":\"n\"}"),
            () => Json(HttpStatusCode.Created, "{\"nonce\":\"n\",\"expires_at\":\"2026-07-22T08:00:30+00:00\",\"extra\":1}"),
            () => Json(HttpStatusCode.Created, "{\"nonce\":\"" + new string('a', 5000) + "\",\"expires_at\":\"2026-07-22T08:00:30+00:00\"}")
        };

        foreach (var responseFactory in cases)
        {
            using var client = CreateClient(
                new ScriptedHandler(_ => responseFactory()),
                new RecordingKeyStore(Key));
            await Assert.ThrowsExactlyAsync<InvalidOperationException>(() => client.OpenAsync(default));
        }
    }

    [TestMethod]
    public async Task SessionHeaderNeverEntersTheUrlAndIsUnavailableAfterDispose()
    {
        var handler = SuccessfulHandler();
        var client = CreateClient(handler, new RecordingKeyStore(Key));
        await client.OpenAsync(default);
        using var request = new HttpRequestMessage(HttpMethod.Get, "v1/failures");

        client.ApplySessionHeader(request);

        Assert.AreEqual("memory-only-token-1234", request.Headers.GetValues("X-Collab-Session").Single());
        Assert.DoesNotContain("token", request.RequestUri!.ToString(), StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("memory-only-token-1234", client.ToString()!);
        client.Dispose();
        await Assert.ThrowsExactlyAsync<ObjectDisposedException>(() => client.OpenAsync(default));
        Assert.ThrowsExactly<ObjectDisposedException>(() => client.ApplySessionHeader(request));
    }

    [TestMethod]
    public void DpapiStoreReadsOnlyTheExpectedProtectedKeyAndReturnsAClone()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllBytes(path, [9, 8, 7]);
            var protector = new FakeProtector(Key);
            var store = new DpapiBootstrapKeyStore(path, protector);

            var first = store.LoadKey();
            first[0] = 0;
            var second = store.LoadKey();

            CollectionAssert.AreEqual(new byte[] { 9, 8, 7 }, protector.LastProtected!);
            CollectionAssert.AreEqual(Key, second);
            Assert.IsTrue(protector.ReturnedBuffers.All(buffer => buffer.All(value => value == 0)));
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static CollabSessionClient CreateClient(
        HttpMessageHandler handler,
        IBootstrapKeyStore keyStore,
        string currentSid = Sid)
    {
        var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:8770/"),
            Timeout = TimeSpan.FromSeconds(2)
        };
        return new CollabSessionClient(
            http,
            new FakeIdentity(currentSid),
            keyStore,
            Sid,
            new FixedTimeProvider(Now));
    }

    private static ScriptedHandler SuccessfulHandler() => new(request =>
        request.RequestUri!.AbsolutePath == "/v1/session/challenge"
            ? Json(HttpStatusCode.Created,
                "{\"nonce\":\"nonce\",\"expires_at\":\"2026-07-22T08:00:30+00:00\"}")
            : Json(HttpStatusCode.Created,
                "{\"token\":\"memory-only-token-1234\",\"session_id\":\"session-1\",\"expires_at\":\"2026-07-22T08:15:00+00:00\"}"));

    private static HttpResponseMessage Json(HttpStatusCode status, string body) => new(status)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json")
    };

    private sealed class ScriptedHandler(Func<HttpRequestMessage, HttpResponseMessage> responder)
        : HttpMessageHandler
    {
        public int Calls { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(responder(request));
        }
    }

    private sealed record FakeIdentity(string CurrentSid) : IWindowsIdentityService;

    private sealed class RecordingKeyStore(byte[] key) : IBootstrapKeyStore
    {
        public int Calls { get; private set; }
        public byte[]? LastReturned { get; private set; }

        public byte[] LoadKey()
        {
            Calls++;
            LastReturned = key.ToArray();
            return LastReturned;
        }
    }

    private sealed class FakeProtector(byte[] clear) : ICurrentUserDataProtector
    {
        public byte[]? LastProtected { get; private set; }
        public List<byte[]> ReturnedBuffers { get; } = [];

        public byte[] Unprotect(byte[] protectedValue)
        {
            LastProtected = protectedValue.ToArray();
            var result = clear.ToArray();
            ReturnedBuffers.Add(result);
            return result;
        }
    }

    private sealed class FixedTimeProvider(DateTimeOffset utcNow) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => utcNow;
    }
}
