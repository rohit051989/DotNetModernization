using System.Diagnostics;
using System.IdentityModel.Selectors;
using System.IdentityModel.Tokens;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Security.Cryptography.X509Certificates;
using System.ServiceModel;
using System.ServiceModel.Security;
using System.Text.Json;

// One probe: a .NET 10 WCF client calls a real service with one binding,
// security mode and credential type, and prints one JSON result. Run inside a
// Linux container; the driver (app.estate.wcf_probe) records it as evidence on
// the WCF client matrix entries it bears on.
//
//   WcfClientProbe <scenario> <address> [--relay <port>] [--server-thumbprint <hex>]
//                  [--client-pfx <path> --client-pfx-password-env <VAR>]
//   WcfClientProbe make-certificates <dir>     (the probe's certificates, as files only)
//
// Certificates are files: the client pfx is loaded by path, the server is trusted
// by its pinned thumbprint. No certificate store is read or written.
//
// --relay forwards 127.0.0.1:<port> to host.docker.internal:<port>, so the
// client addresses the service as localhost — the host name its certificate
// carries and the only one IIS Express accepts — while the bytes go to the
// Windows host. A TCP relay only: it never reads or changes what passes.

if (args.Length == 2 && args[0] == "make-certificates")
{
    Certificates.Make(args[1]);
    return 0;
}

var arguments = Args.Parse(args);
var result = new Dictionary<string, object?>
{
    ["scenario"] = arguments.Scenario,
    ["address"] = arguments.Address,
    ["os"] = RuntimeInformation.OSDescription,
    ["framework"] = RuntimeInformation.FrameworkDescription,
    ["wcfClient"] = typeof(ChannelFactory).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
    // Message security signs with it: which version ran is part of the evidence.
    ["cryptographyXml"] = typeof(System.Security.Cryptography.Xml.SignedXml).Assembly
        .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
};
var watch = Stopwatch.StartNew();
using var relay = arguments.RelayPort is { } port ? Relay.Start(port) : null;
try
{
    var (operation, response) = Scenarios.Run(arguments);
    result["outcome"] = "passed";
    result["operation"] = operation;
    result["response"] = response;
}
catch (Exception error)
{
    result["outcome"] = "failed";
    result["error"] = $"{error.GetType().FullName}: {error.Message}";
    result["inner"] = error.InnerException is { } inner ? $"{inner.GetType().FullName}: {inner.Message}" : null;
    result["detail"] = error.ToString();
}

result["durationMs"] = watch.ElapsedMilliseconds;
Console.WriteLine(JsonSerializer.Serialize(result));
return result["outcome"] as string == "passed" ? 0 : 1;

sealed record Args(string Scenario, string Address, int? RelayPort, string? ServerThumbprint, string? ClientPfx, string? ClientPfxPassword)
{
    public static Args Parse(string[] args)
    {
        string? Option(string name) => Array.IndexOf(args, name) is var i and >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        return new Args(args[0], args[1], Option("--relay") is { } p ? int.Parse(p) : null, Option("--server-thumbprint"),
            Option("--client-pfx"), Option("--client-pfx-password-env") is { } v ? Environment.GetEnvironmentVariable(v) : null);
    }
}

static class Scenarios
{
    public static (string Operation, string Response) Run(Args a)
    {
        switch (a.Scenario)
        {
            case "basicHttp-None-None":
            {
                var binding = new BasicHttpBinding(BasicHttpSecurityMode.None);
                var channel = Open<IFundsTransferWSSoap>(binding, a);
                return ("FundsTransferWS.Ping", channel.Ping());
            }
            case "basicHttp-Transport-None":
            {
                var binding = new BasicHttpBinding(BasicHttpSecurityMode.Transport);
                binding.Security.Transport.ClientCredentialType = HttpClientCredentialType.None;
                return ("IUtilityService.Ping", Open<IUtilityService>(binding, a).Ping());
            }
            case "netTcp-Transport-None":
            {
                var binding = new NetTcpBinding(SecurityMode.Transport);
                binding.Security.Transport.ClientCredentialType = TcpClientCredentialType.None;
                return ("IUtilityService.Ping", Open<IUtilityService>(binding, a).Ping());
            }
            case "netTcp-Transport-Certificate":
            {
                var binding = new NetTcpBinding(SecurityMode.Transport);
                binding.Security.Transport.ClientCredentialType = TcpClientCredentialType.Certificate;
                var account = Open<IAccountService>(binding, a).GetAccount("CUST-001");
                return ("IAccountService.GetAccount(CUST-001)", $"{account.CustomerId} {account.DisplayName}");
            }
            case "wsHttp-TransportWithMessageCredential-Certificate":
            {
                var binding = new WSHttpBinding(SecurityMode.TransportWithMessageCredential);
                binding.Security.Message.ClientCredentialType = MessageCredentialType.Certificate;
                var account = Open<IAccountService>(binding, a).GetAccount("CUST-001");
                return ("IAccountService.GetAccount(CUST-001)", $"{account.CustomerId} {account.DisplayName}");
            }
            default:
                throw new ArgumentException($"unknown scenario {a.Scenario}");
        }
    }

    private static T Open<T>(System.ServiceModel.Channels.Binding binding, Args a)
    {
        binding.OpenTimeout = binding.SendTimeout = binding.ReceiveTimeout = TimeSpan.FromSeconds(30);
        var factory = new ChannelFactory<T>(binding, new EndpointAddress(a.Address));
        if (a.ServerThumbprint is { } thumbprint)
        {
            // The service's own certificate, pinned by thumbprint: the container trusts nothing else.
            factory.Credentials.ServiceCertificate.SslCertificateAuthentication = new X509ServiceCertificateAuthentication
            {
                CertificateValidationMode = X509CertificateValidationMode.Custom,
                CustomCertificateValidator = new PinnedThumbprint(thumbprint),
                RevocationMode = X509RevocationMode.NoCheck,
            };
        }

        if (a.ClientPfx is { } pfx)
        {
            factory.Credentials.ClientCertificate.Certificate = X509CertificateLoader.LoadPkcs12FromFile(pfx, a.ClientPfxPassword);
        }

        return factory.CreateChannel();
    }
}

sealed class PinnedThumbprint(string thumbprint) : X509CertificateValidator
{
    public override void Validate(X509Certificate2 certificate)
    {
        if (!string.Equals(certificate.Thumbprint, thumbprint, StringComparison.OrdinalIgnoreCase))
        {
            throw new SecurityTokenValidationException($"server certificate {certificate.Thumbprint} is not the pinned {thumbprint}");
        }
    }
}

/// <summary>
/// WcfClientProbe make-certificates &lt;dir&gt;: the probe's certificates, made in memory and
/// written only as files to a scratch folder — never to or from a certificate store.
/// server.pfx (CN=localhost, the name the client addresses), client.pfx (client
/// authentication), their public halves server.cer and client.cer, and pfx.password, a
/// random password for both .pfx files. The server pins client.cer; the client pins
/// server.cer. Valid 90 days: probe material, not anyone's identity.
/// </summary>
static class Certificates
{
    public static void Make(string directory)
    {
        Directory.CreateDirectory(directory);
        var password = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(24));
        Write(directory, "server", "CN=localhost", "1.3.6.1.5.5.7.3.1", X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, password, dns: "localhost");
        Write(directory, "client", "CN=WcfProbeClient", "1.3.6.1.5.5.7.3.2", X509KeyUsageFlags.DigitalSignature, password, dns: null);
        File.WriteAllText(Path.Combine(directory, "pfx.password"), password);
        Console.WriteLine($"certificates written to {Path.GetFullPath(directory)}");
    }

    private static void Write(string directory, string name, string subject, string usage, X509KeyUsageFlags keyUsage, string password, string? dns)
    {
        using var key = System.Security.Cryptography.RSA.Create(2048);
        var request = new CertificateRequest(subject, key, System.Security.Cryptography.HashAlgorithmName.SHA256,
            System.Security.Cryptography.RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(new X509KeyUsageExtension(keyUsage, true));
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension([new System.Security.Cryptography.Oid(usage)], false));
        if (dns is not null)
        {
            var names = new SubjectAlternativeNameBuilder();
            names.AddDnsName(dns);
            request.CertificateExtensions.Add(names.Build());
        }

        using var certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(90));
        File.WriteAllBytes(Path.Combine(directory, $"{name}.pfx"),
            certificate.ExportPkcs12(Pkcs12ExportPbeParameters.Pbes2Aes256Sha256, password));
        File.WriteAllBytes(Path.Combine(directory, $"{name}.cer"), certificate.Export(X509ContentType.Cert));
    }
}

/// <summary>127.0.0.1:port → host.docker.internal:port, byte for byte.</summary>
sealed class Relay : IDisposable
{
    private readonly TcpListener _listener;

    private Relay(TcpListener listener) => _listener = listener;

    public static Relay Start(int port)
    {
        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        var relay = new Relay(listener);
        _ = Task.Run(async () =>
        {
            while (true)
            {
                TcpClient inbound;
                try { inbound = await listener.AcceptTcpClientAsync(); }
                catch (ObjectDisposedException) { return; }
                catch (SocketException) { return; }
                _ = Task.Run(async () =>
                {
                    using var client = inbound;
                    using var outbound = new TcpClient();
                    await outbound.ConnectAsync("host.docker.internal", port);
                    var a = client.GetStream();
                    var b = outbound.GetStream();
                    await Task.WhenAny(a.CopyToAsync(b), b.CopyToAsync(a));
                });
            }
        });
        return relay;
    }

    public void Dispose() => _listener.Stop();
}

// ---- the contracts, as the services declare them

[ServiceContract(Namespace = "http://fundstransfer.corp.example/FundsTransferWS/")]
[XmlSerializerFormat]
public interface IFundsTransferWSSoap
{
    [OperationContract(Action = "http://fundstransfer.corp.example/FundsTransferWS/Ping", ReplyAction = "*")]
    string Ping();
}

[ServiceContract(Namespace = "http://wcfcatalog.dev/contracts/2026/01")]
public interface IUtilityService
{
    [OperationContract]
    string Ping();
}

[ServiceContract(Namespace = "http://wcfcatalog.dev/contracts/2026/01")]
public interface IAccountService
{
    [OperationContract]
    Account GetAccount(string customerId);
}

[DataContract(Namespace = "http://wcfcatalog.dev/contracts/2026/01")]
public class Account
{
    [DataMember(Order = 1)] public string? CustomerId { get; set; }
    [DataMember(Order = 2)] public string? DisplayName { get; set; }
    [DataMember(Order = 3)] public string? Email { get; set; }
    [DataMember(Order = 4)] public string? Phone { get; set; }
    [DataMember(Order = 5)] public DateTime CreatedUtc { get; set; }
}
