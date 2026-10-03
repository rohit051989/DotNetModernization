using NuGet.Common;
using NuGet.Configuration;
using NuGet.Credentials;
using NuGet.Protocol;
using NuGet.Protocol.Plugins;

namespace Fingerprinting.Dependencies;

/// <summary>
/// Part B4: feed authentication is NuGet's own. <c>packageSourceCredentials</c>
/// in NuGet.config and the <c>NuGetPackageSourceCredentials_{name}</c>
/// environment variables reach each <see cref="NuGet.Configuration.PackageSource"/>
/// through NuGet's settings; credential providers (the Azure Artifacts
/// provider, an Artifactory plugin) are installed here, non-interactively —
/// a step cannot prompt. Credentials live in NuGet's memory for the run;
/// this step never reads, logs or stores one.
/// </summary>
public static class FeedCredentials
{
    private static bool _configured;

    public static void Configure()
    {
        if (_configured) return;
        _configured = true;
        var providers = new AsyncLazy<IEnumerable<ICredentialProvider>>(async () =>
            await new SecurePluginCredentialProviderBuilder(PluginManager.Instance, canShowDialog: false, NullLogger.Instance).BuildAllAsync());
        HttpHandlerResourceV3.CredentialService = new Lazy<ICredentialService>(() =>
            new CredentialService(providers, nonInteractive: true, handlesDefaultCredentials: true));
    }
}
