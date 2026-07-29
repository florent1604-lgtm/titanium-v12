using System.IO;
using System.Security.Cryptography;

namespace Titanium.CommandDeck.Services;

public interface IBootstrapKeyStore
{
    byte[] LoadKey();
}

public interface ICurrentUserDataProtector
{
    byte[] Unprotect(byte[] protectedValue);
}

public sealed class DpapiCurrentUserDataProtector : ICurrentUserDataProtector
{
    public byte[] Unprotect(byte[] protectedValue) => ProtectedData.Unprotect(
        protectedValue,
        optionalEntropy: null,
        DataProtectionScope.CurrentUser);
}

public sealed class DpapiBootstrapKeyStore : IBootstrapKeyStore
{
    private const int MaximumProtectedKeyBytes = 16 * 1024;
    private readonly string _path;
    private readonly ICurrentUserDataProtector _protector;

    public DpapiBootstrapKeyStore()
        : this(DefaultPath(), new DpapiCurrentUserDataProtector())
    {
    }

    public DpapiBootstrapKeyStore(string path, ICurrentUserDataProtector protector)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        _path = Path.GetFullPath(path);
        _protector = protector ?? throw new ArgumentNullException(nameof(protector));
    }

    public byte[] LoadKey()
    {
        var info = new FileInfo(_path);
        if (!info.Exists || info.Length is <= 0 or > MaximumProtectedKeyBytes)
        {
            throw new InvalidOperationException("BOOTSTRAP_KEY_UNAVAILABLE");
        }
        if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidOperationException("BOOTSTRAP_KEY_UNAVAILABLE");
        }

        var protectedValue = File.ReadAllBytes(_path);
        try
        {
            var clear = _protector.Unprotect(protectedValue);
            try
            {
                if (clear.Length != 32)
                {
                    throw new InvalidOperationException("BOOTSTRAP_KEY_INVALID");
                }
                return clear.ToArray();
            }
            finally
            {
                CryptographicOperations.ZeroMemory(clear);
            }
        }
        catch (InvalidOperationException)
        {
            throw;
        }
        catch (Exception)
        {
            throw new InvalidOperationException("BOOTSTRAP_KEY_UNAVAILABLE");
        }
        finally
        {
            CryptographicOperations.ZeroMemory(protectedValue);
        }
    }

    private static string DefaultPath()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local))
        {
            throw new InvalidOperationException("LOCAL_APP_DATA_UNAVAILABLE");
        }
        return Path.Combine(local, "Titanium", "CommandDeck", "session.key.dpapi");
    }
}
