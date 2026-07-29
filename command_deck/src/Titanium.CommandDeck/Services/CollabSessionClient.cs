using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Titanium.CommandDeck.Services;

public sealed class CollabSessionClient : IDisposable
{
    private const string SessionHeader = "X-Collab-Session";
    private const int ChallengeLimit = 4 * 1024;
    private const int SessionLimit = 8 * 1024;
    private static readonly string[] TimestampFormats =
    [
        "yyyy-MM-dd'T'HH:mm:sszzz",
        "yyyy-MM-dd'T'HH:mm:ss.FFFFFFFzzz"
    ];

    private readonly HttpClient _http;
    private readonly IWindowsIdentityService _identity;
    private readonly IBootstrapKeyStore _keyStore;
    private readonly string _expectedSid;
    private readonly TimeProvider _clock;
    private readonly SemaphoreSlim _openGate = new(1, 1);
    private readonly object _tokenGate = new();
    private char[]? _token;
    private bool _disposed;

    public CollabSessionClient(
        HttpClient http,
        IWindowsIdentityService identity,
        IBootstrapKeyStore keyStore,
        string expectedWindowsSid,
        TimeProvider? clock = null)
    {
        _http = http ?? throw new ArgumentNullException(nameof(http));
        _identity = identity ?? throw new ArgumentNullException(nameof(identity));
        _keyStore = keyStore ?? throw new ArgumentNullException(nameof(keyStore));
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedWindowsSid);
        _expectedSid = expectedWindowsSid;
        _clock = clock ?? TimeProvider.System;
        if (_http.BaseAddress is null || !OriginPolicy.IsExactHttpOrigin(_http.BaseAddress))
        {
            throw new ArgumentException("COLLABHUB_ORIGIN_REQUIRED", nameof(http));
        }
    }

    public bool IsOpen
    {
        get
        {
            lock (_tokenGate)
            {
                return !_disposed && _token is not null && _clock.GetUtcNow() < ExpiresAt;
            }
        }
    }

    public DateTimeOffset? ExpiresAt { get; private set; }

    public async Task OpenAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await _openGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ThrowIfDisposed();
            ClearToken();
            var sid = _identity.CurrentSid;
            if (!string.Equals(sid, _expectedSid, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("WINDOWS_SID_REJECTED");
            }

            var challenge = await PostJsonAsync(
                "v1/session/challenge",
                content: null,
                HttpStatusCode.Created,
                ChallengeLimit,
                cancellationToken).ConfigureAwait(false);
            var (nonce, challengeExpiryText, challengeExpiry) = ParseChallenge(challenge);
            var now = _clock.GetUtcNow();
            if (challengeExpiry <= now || challengeExpiry > now.AddMinutes(2))
            {
                throw new InvalidOperationException("CHALLENGE_EXPIRED");
            }

            var key = _keyStore.LoadKey();
            string proof;
            var proofInput = Encoding.UTF8.GetBytes($"{sid}|{nonce}|{challengeExpiryText}");
            try
            {
                if (key.Length != 32)
                {
                    throw new InvalidOperationException("BOOTSTRAP_KEY_INVALID");
                }
                proof = Convert.ToHexString(HMACSHA256.HashData(key, proofInput))
                    .ToLowerInvariant();
            }
            finally
            {
                CryptographicOperations.ZeroMemory(key);
                CryptographicOperations.ZeroMemory(proofInput);
            }

            var requestBody = JsonSerializer.Serialize(new { sid, nonce, proof });
            var sessionBody = await PostJsonAsync(
                "v1/session/windows",
                new StringContent(requestBody, Encoding.UTF8, "application/json"),
                HttpStatusCode.Created,
                SessionLimit,
                cancellationToken).ConfigureAwait(false);
            string token;
            DateTimeOffset expiresAt;
            try
            {
                (token, expiresAt) = ParseSession(sessionBody);
            }
            finally
            {
                CryptographicOperations.ZeroMemory(sessionBody);
            }
            if (expiresAt <= _clock.GetUtcNow() || expiresAt > _clock.GetUtcNow().AddHours(24))
            {
                throw new InvalidOperationException("SESSION_EXPIRATION_INVALID");
            }

            lock (_tokenGate)
            {
                ThrowIfDisposed();
                _token = token.ToCharArray();
                ExpiresAt = expiresAt;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (InvalidOperationException)
        {
            ClearToken();
            throw;
        }
        catch (Exception)
        {
            ClearToken();
            throw new InvalidOperationException("SESSION_OPEN_FAILED");
        }
        finally
        {
            _openGate.Release();
        }
    }

    public void ApplySessionHeader(HttpRequestMessage request)
    {
        ArgumentNullException.ThrowIfNull(request);
        UseSessionToken(token =>
        {
            request.Headers.Remove(SessionHeader);
            request.Headers.TryAddWithoutValidation(SessionHeader, token);
        });
    }

    internal void UseSessionToken(Action<string> consumer)
    {
        ArgumentNullException.ThrowIfNull(consumer);
        lock (_tokenGate)
        {
            ThrowIfDisposed();
            if (_token is null || ExpiresAt is null || _clock.GetUtcNow() >= ExpiresAt)
            {
                ClearTokenUnsafe();
                throw new InvalidOperationException("SESSION_UNAVAILABLE");
            }
            consumer(new string(_token));
        }
    }

    public void Dispose()
    {
        lock (_tokenGate)
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            ClearTokenUnsafe();
        }
        _http.Dispose();
    }

    public override string ToString() => $"{nameof(CollabSessionClient)}(open={IsOpen})";

    private async Task<byte[]> PostJsonAsync(
        string relativeUri,
        HttpContent? content,
        HttpStatusCode expectedStatus,
        int maximumBytes,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, relativeUri)
        {
            Content = content
        };
        using var response = await _http.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken).ConfigureAwait(false);
        if (response.StatusCode != expectedStatus ||
            response.Content.Headers.ContentType?.MediaType != "application/json")
        {
            throw new InvalidOperationException("SESSION_PROTOCOL_REJECTED");
        }
        if (response.Content.Headers.ContentLength > maximumBytes)
        {
            throw new InvalidOperationException("SESSION_RESPONSE_TOO_LARGE");
        }

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken)
            .ConfigureAwait(false);
        using var buffer = new MemoryStream();
        var chunk = new byte[1024];
        while (true)
        {
            var read = await stream.ReadAsync(chunk, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }
            if (buffer.Length + read > maximumBytes)
            {
                throw new InvalidOperationException("SESSION_RESPONSE_TOO_LARGE");
            }
            buffer.Write(chunk, 0, read);
        }
        return buffer.ToArray();
    }

    private static (string Nonce, string ExpiresAtText, DateTimeOffset ExpiresAt) ParseChallenge(byte[] body)
    {
        using var document = ParseStrictObject(body, ["nonce", "expires_at"]);
        var nonce = BoundedString(document.RootElement, "nonce", 1, 256);
        var expiresAtText = BoundedString(document.RootElement, "expires_at", 1, 64);
        var expiresAt = ParseUtcTimestamp(expiresAtText);
        return (nonce, expiresAtText, expiresAt);
    }

    private static (string Token, DateTimeOffset ExpiresAt) ParseSession(byte[] body)
    {
        using var document = ParseStrictObject(body, ["token", "session_id", "expires_at"]);
        var token = BoundedString(document.RootElement, "token", 20, 256);
        _ = BoundedString(document.RootElement, "session_id", 1, 128);
        var expiresAt = ParseUtcTimestamp(BoundedString(document.RootElement, "expires_at", 1, 64));
        return (token, expiresAt);
    }

    private static JsonDocument ParseStrictObject(byte[] body, string[] expectedProperties)
    {
        try
        {
            var document = JsonDocument.Parse(body, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 4
            });
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                document.Dispose();
                throw new InvalidOperationException("SESSION_SCHEMA_REJECTED");
            }
            var names = document.RootElement.EnumerateObject().Select(property => property.Name).ToArray();
            if (names.Length != expectedProperties.Length ||
                names.Distinct(StringComparer.Ordinal).Count() != names.Length ||
                !names.Order(StringComparer.Ordinal).SequenceEqual(
                    expectedProperties.Order(StringComparer.Ordinal),
                    StringComparer.Ordinal))
            {
                document.Dispose();
                throw new InvalidOperationException("SESSION_SCHEMA_REJECTED");
            }
            return document;
        }
        catch (JsonException)
        {
            throw new InvalidOperationException("SESSION_SCHEMA_REJECTED");
        }
    }

    private static string BoundedString(JsonElement root, string property, int minimum, int maximum)
    {
        var element = root.GetProperty(property);
        if (element.ValueKind != JsonValueKind.String)
        {
            throw new InvalidOperationException("SESSION_SCHEMA_REJECTED");
        }
        var value = element.GetString()!;
        if (value.Length < minimum || value.Length > maximum || string.IsNullOrWhiteSpace(value))
        {
            throw new InvalidOperationException("SESSION_SCHEMA_REJECTED");
        }
        return value;
    }

    private static DateTimeOffset ParseUtcTimestamp(string value)
    {
        if (!value.EndsWith("+00:00", StringComparison.Ordinal) ||
            !DateTimeOffset.TryParseExact(
                value,
                TimestampFormats,
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var parsed) ||
            parsed.Offset != TimeSpan.Zero)
        {
            throw new InvalidOperationException("SESSION_TIMESTAMP_REJECTED");
        }
        return parsed;
    }

    private void ClearToken()
    {
        lock (_tokenGate)
        {
            ClearTokenUnsafe();
        }
    }

    private void ClearTokenUnsafe()
    {
        if (_token is not null)
        {
            Array.Fill(_token, '\0');
            _token = null;
        }
        ExpiresAt = null;
    }

    private void ThrowIfDisposed()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
    }
}
