using System.Security.Principal;

namespace Titanium.CommandDeck.Services;

public interface IWindowsIdentityService
{
    string CurrentSid { get; }
}

public sealed class WindowsIdentityService : IWindowsIdentityService
{
    public string CurrentSid
    {
        get
        {
            using var identity = WindowsIdentity.GetCurrent(TokenAccessLevels.Query);
            return identity.User?.Value
                ?? throw new InvalidOperationException("WINDOWS_IDENTITY_UNAVAILABLE");
        }
    }
}
