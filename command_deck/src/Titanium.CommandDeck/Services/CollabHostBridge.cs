using System.Text;
using System.Text.Json;

namespace Titanium.CommandDeck.Services;

public sealed record HostIntent(string Type, string PayloadJson);

public sealed record HostIntentResult(bool Confirmed, string ReasonCode);

public interface IHostConfirmation
{
    Task<bool> ConfirmAsync(HostIntent intent, CancellationToken cancellationToken);
}

public static class OriginPolicy
{
    public static readonly Uri UiUri = new("http://127.0.0.1:8770/ui/");

    public static bool IsExactHttpOrigin(Uri uri) =>
        uri.IsAbsoluteUri &&
        string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.Ordinal) &&
        string.Equals(uri.Host, "127.0.0.1", StringComparison.Ordinal) &&
        uri.Port == 8770 &&
        string.IsNullOrEmpty(uri.UserInfo);

    public static bool IsAllowedNavigation(Uri uri) => IsExactHttpOrigin(uri);

    public static bool IsAllowedWebMessage(Uri uri) => IsExactHttpOrigin(uri);

    public static bool IsAllowedResource(Uri uri)
    {
        if (IsExactHttpOrigin(uri))
        {
            return true;
        }
        return uri.IsAbsoluteUri &&
            string.Equals(uri.Scheme, "ws", StringComparison.Ordinal) &&
            string.Equals(uri.Host, "127.0.0.1", StringComparison.Ordinal) &&
            uri.Port == 8770 &&
            string.IsNullOrEmpty(uri.UserInfo) &&
            string.Equals(uri.AbsolutePath, "/v1/ws", StringComparison.Ordinal);
    }

    public static bool RequiresSessionHeader(Uri uri) =>
        (IsExactHttpOrigin(uri) &&
            uri.AbsolutePath.StartsWith("/v1/", StringComparison.Ordinal)) ||
        (IsAllowedResource(uri) &&
            string.Equals(uri.Scheme, "ws", StringComparison.Ordinal));
}

public sealed class CollabHostBridge
{
    public const int MaximumIntentBytes = 64 * 1024;
    private static readonly IReadOnlyDictionary<string, Schema> Schemas =
        new Dictionary<string, Schema>(StringComparer.Ordinal)
        {
            ["chat.publish"] = new(["content"], ["target", "task_id", "in_reply_to"]),
            ["task.create"] = new(["title", "owner", "priority"], []),
            ["task.retry.request"] = new(["task_id"], []),
            ["action.preview"] = new(["action"], ["parameters"]),
            ["host.open_vscode"] = new([], ["path"])
        };

    private readonly IHostConfirmation _confirmation;

    public CollabHostBridge(IHostConfirmation confirmation)
    {
        _confirmation = confirmation ?? throw new ArgumentNullException(nameof(confirmation));
    }

    public async Task<HostIntentResult> HandleAsync(
        HostIntent intent,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(intent);
        Validate(intent);
        try
        {
            var confirmed = await _confirmation.ConfirmAsync(intent, cancellationToken)
                .ConfigureAwait(false);
            return confirmed
                ? new HostIntentResult(true, "CONFIRMED_PENDING_BROKER")
                : new HostIntentResult(false, "USER_REJECTED");
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            return new HostIntentResult(false, "CONFIRMATION_UNAVAILABLE");
        }
    }

    public Task<HostIntentResult> HandleWebMessageAsync(
        Uri source,
        string rawJson,
        CancellationToken cancellationToken)
    {
        if (source is null || !OriginPolicy.IsAllowedWebMessage(source))
        {
            throw new InvalidOperationException("WEB_MESSAGE_ORIGIN_REJECTED");
        }
        if (rawJson is null || Encoding.UTF8.GetByteCount(rawJson) > MaximumIntentBytes)
        {
            throw new InvalidOperationException("WEB_MESSAGE_SIZE_REJECTED");
        }

        try
        {
            using var document = JsonDocument.Parse(rawJson, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 10
            });
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidOperationException("WEB_MESSAGE_SCHEMA_REJECTED");
            }
            var properties = document.RootElement.EnumerateObject().ToArray();
            if (properties.Select(property => property.Name).Distinct(StringComparer.Ordinal).Count() !=
                properties.Length)
            {
                throw new InvalidOperationException("WEB_MESSAGE_SCHEMA_REJECTED");
            }
            if (!document.RootElement.TryGetProperty("type", out var typeElement) ||
                typeElement.ValueKind != JsonValueKind.String)
            {
                throw new InvalidOperationException("WEB_MESSAGE_SCHEMA_REJECTED");
            }
            var type = typeElement.GetString()!;
            var payload = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            foreach (var property in properties)
            {
                if (property.Name != "type")
                {
                    payload.Add(property.Name, property.Value.Clone());
                }
            }
            return HandleAsync(
                new HostIntent(type, JsonSerializer.Serialize(payload)),
                cancellationToken);
        }
        catch (JsonException)
        {
            throw new InvalidOperationException("WEB_MESSAGE_SCHEMA_REJECTED");
        }
    }

    private static void Validate(HostIntent intent)
    {
        if (!Schemas.TryGetValue(intent.Type, out var schema))
        {
            throw new InvalidOperationException("HOST_INTENT_NOT_ALLOWED");
        }
        if (string.IsNullOrEmpty(intent.PayloadJson) ||
            Encoding.UTF8.GetByteCount(intent.PayloadJson) > MaximumIntentBytes)
        {
            throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
        }

        try
        {
            using var document = JsonDocument.Parse(intent.PayloadJson, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 9
            });
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
            }
            var fields = root.EnumerateObject().ToArray();
            var names = fields.Select(field => field.Name).ToArray();
            if (names.Distinct(StringComparer.Ordinal).Count() != names.Length ||
                names.Any(name => !schema.Allowed.Contains(name)) ||
                schema.Required.Any(required => !names.Contains(required, StringComparer.Ordinal)))
            {
                throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
            }

            ValidateFields(intent.Type, root);
            ValidateJson(root, 0);
        }
        catch (JsonException)
        {
            throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
        }
    }

    private static void ValidateFields(string type, JsonElement root)
    {
        switch (type)
        {
            case "chat.publish":
                Text(root, "content", 1, 8000);
                OptionalText(root, "target", 256);
                OptionalText(root, "task_id", 256);
                OptionalText(root, "in_reply_to", 256);
                break;
            case "task.create":
                Text(root, "title", 1, 512);
                Text(root, "owner", 1, 128);
                Text(root, "priority", 1, 32);
                break;
            case "task.retry.request":
                Text(root, "task_id", 1, 256);
                break;
            case "action.preview":
                Text(root, "action", 1, 128);
                if (root.TryGetProperty("parameters", out var parameters) &&
                    parameters.ValueKind != JsonValueKind.Object)
                {
                    throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
                }
                break;
            case "host.open_vscode":
                OptionalText(root, "path", 1024);
                break;
        }
    }

    private static void OptionalText(JsonElement root, string property, int maximum)
    {
        if (root.TryGetProperty(property, out _))
        {
            Text(root, property, 1, maximum);
        }
    }

    private static void Text(JsonElement root, string property, int minimum, int maximum)
    {
        var value = root.GetProperty(property);
        if (value.ValueKind != JsonValueKind.String)
        {
            throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
        }
        var text = value.GetString()!;
        if (text.Length < minimum || text.Length > maximum)
        {
            throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
        }
    }

    private static void ValidateJson(JsonElement value, int depth)
    {
        if (depth > 8)
        {
            throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
        }
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                var properties = value.EnumerateObject().ToArray();
                if (properties.Length > 100 ||
                    properties.Select(property => property.Name)
                        .Distinct(StringComparer.Ordinal).Count() != properties.Length ||
                    properties.Any(property => property.Name.Length > 128 ||
                        property.Name is "__proto__" or "constructor"))
                {
                    throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
                }
                foreach (var property in properties)
                {
                    ValidateJson(property.Value, depth + 1);
                }
                break;
            case JsonValueKind.Array:
                var items = value.EnumerateArray().ToArray();
                if (items.Length > 100)
                {
                    throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
                }
                foreach (var item in items)
                {
                    ValidateJson(item, depth + 1);
                }
                break;
            case JsonValueKind.String:
                if (value.GetString()!.Length > 8192)
                {
                    throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
                }
                break;
            case JsonValueKind.Number:
                if (!value.TryGetDouble(out var number) || !double.IsFinite(number))
                {
                    throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
                }
                break;
            case JsonValueKind.True:
            case JsonValueKind.False:
            case JsonValueKind.Null:
                break;
            default:
                throw new InvalidOperationException("HOST_INTENT_SCHEMA_REJECTED");
        }
    }

    private sealed class Schema(IEnumerable<string> required, IEnumerable<string> optional)
    {
        public HashSet<string> Required { get; } = new(required, StringComparer.Ordinal);
        public HashSet<string> Allowed { get; } = new(
            required.Concat(optional),
            StringComparer.Ordinal);
    }
}
