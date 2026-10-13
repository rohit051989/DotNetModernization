using System;
using System.IdentityModel.Selectors;
using System.IdentityModel.Tokens;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.ServiceModel;
using System.ServiceModel.Channels;
using System.ServiceModel.Security;
using System.ServiceModel.Security.Tokens;
using System.Threading;
using System.Threading.Tasks;

// The services the WCF client matrix probe calls: the WCF sample's own service
// types (WcfCatalog.Services, loaded by path from a copy of the sample), with the
// bindings the sample hosts them on — Catalog.Host's netTcp, Hosting.Iis's HTTPS.
//
//   ProbeServices --services-bin <dir> --certs <dir>
//
// Certificates come from files in --certs (WcfClientProbe make-certificates writes
// them): server.pfx with pfx.password, and client.cer. Never from or into a
// certificate store: the server certificate is loaded without PersistKeySet, so its
// key lives in a temporary key container deleted when the process ends, and the
// client certificate is trusted by pinning its thumbprint, not by a trust store.
//
// HTTPS: .NET Framework WCF hosts HTTP only through http.sys, which takes its
// certificate from the LocalMachine store. So the HTTP services listen on plain
// http://localhost:8601 (an exact localhost registration needs no admin), and a TLS
// terminator on 44301 — SslStream with the certificate from the file — forwards
// the decrypted bytes to it. The client sees HTTPS to https://localhost:44301, as
// it would against IIS. wsHttp TransportWithMessageCredential is the sample's
// binding with AllowInsecureTransport on the server's security element: the
// standard SSL-offload arrangement; the client's messages are unchanged.
//
// A second terminator on 44302 requires a client certificate and accepts only the
// pinned client.cer, as IIS does with "Require SSL" and client certificates
// required: basicHttps Transport/Certificate. The service behind it is the same
// basicHttp endpoint; TLS is where a Transport client certificate is checked.

internal static class Program
{
    private const int HttpPort = 8601;
    private const int HttpsPort = 44301;
    private const int HttpsClientCertificatePort = 44302;

    private static int Main(string[] args)
    {
        string Option(string name)
        {
            var i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }

        var bin = Path.GetFullPath(Option("--services-bin") ?? throw new ArgumentException("--services-bin is required"));
        var certs = Path.GetFullPath(Option("--certs") ?? throw new ArgumentException("--certs is required"));
        var password = File.ReadAllText(Path.Combine(certs, "pfx.password")).Trim();
        var server = new X509Certificate2(Path.Combine(certs, "server.pfx"), password, X509KeyStorageFlags.UserKeySet);
        var client = new X509Certificate2(Path.Combine(certs, "client.cer"));

        var contracts = Assembly.LoadFrom(Path.Combine(bin, "WcfCatalog.Contracts.dll"));
        var services = Assembly.LoadFrom(Path.Combine(bin, "WcfCatalog.Services.dll"));
        Type Service(string name) => services.GetType("WcfCatalog.Services." + name, throwOnError: true);
        Type Contract(string name) => contracts.GetType("WcfCatalog.Contracts." + name, throwOnError: true);

        var hosts = new[]
        {
            Tcp(Service("UtilityService"), Contract("IUtilityService"), "Utility", 8101, server, null),
            Tcp(Service("AccountService"), Contract("IAccountService"), "Account", 8202, server, client),
            BasicHttps(Service("UtilityService"), Contract("IUtilityService"), "Utility.svc"),
            WsHttpsMessageCertificate(Service("AccountService"), Contract("IAccountService"), "Account.svc", client),
        };
        foreach (var host in hosts)
        {
            host.Open();
            foreach (var endpoint in host.Description.Endpoints)
            {
                Console.WriteLine($"open: {endpoint.Address.Uri} ({endpoint.Binding.Name}) listening on {endpoint.ListenUri}");
            }
        }

        using (var terminator = TlsTerminator.Start(HttpsPort, HttpPort, server, null))
        using (var mutual = TlsTerminator.Start(HttpsClientCertificatePort, HttpPort, server, client))
        {
            Console.WriteLine($"TLS terminator: https://localhost:{HttpsPort} -> http://localhost:{HttpPort} " +
                              $"(server certificate {server.Subject}, {server.Thumbprint}, from {Path.Combine(certs, "server.pfx")})");
            Console.WriteLine($"TLS terminator: https://localhost:{HttpsClientCertificatePort} -> http://localhost:{HttpPort} " +
                              $"(client certificate required, pinned {client.Thumbprint})");
            Console.WriteLine("Ctrl+C to stop.");
            var stop = new ManualResetEvent(false);
            Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Set(); };
            stop.WaitOne();
        }

        foreach (var host in hosts)
        {
            host.Abort();
        }

        server.Dispose();
        return 0;
    }

    /// <summary>Catalog.Host's netTcp: Transport, EncryptAndSign; mutual TLS when a client certificate is pinned.</summary>
    private static ServiceHost Tcp(Type service, Type contract, string name, int port, X509Certificate2 server, X509Certificate2 client)
    {
        var address = new Uri($"net.tcp://localhost:{port}/{name}");
        var host = new ServiceHost(service, address);
        var binding = new NetTcpBinding(SecurityMode.Transport);
        binding.Security.Transport.ClientCredentialType = client is null ? TcpClientCredentialType.None : TcpClientCredentialType.Certificate;
        binding.Security.Transport.ProtectionLevel = ProtectionLevel.EncryptAndSign;
        host.AddServiceEndpoint(contract, binding, address);
        host.Credentials.ServiceCertificate.Certificate = server;
        if (client is not null)
        {
            Pin(host, client);
        }

        return host;
    }

    /// <summary>Hosting.Iis's basicHttpBinding Transport/None, behind the TLS terminator.</summary>
    private static ServiceHost BasicHttps(Type service, Type contract, string path)
    {
        var host = new ServiceHost(service);
        var binding = new BasicHttpBinding(BasicHttpSecurityMode.None) { HostNameComparisonMode = HostNameComparisonMode.Exact };
        // basicHttp sends no WS-Addressing To: the dispatcher compares the address it received on, so the
        // endpoint's address is the one it listens on.
        host.AddServiceEndpoint(contract, binding, new Uri($"http://localhost:{HttpPort}/{path}"));
        return host;
    }

    /// <summary>Hosting.Iis's wsHttpBinding TransportWithMessageCredential/Certificate, behind the TLS terminator.</summary>
    private static ServiceHost WsHttpsMessageCertificate(Type service, Type contract, string path, X509Certificate2 client)
    {
        var host = new ServiceHost(service);
        var sample = new WSHttpBinding(SecurityMode.TransportWithMessageCredential);
        sample.Security.Message.ClientCredentialType = MessageCredentialType.Certificate;
        var elements = sample.CreateBindingElements();
        foreach (var security in elements.OfType<SecurityBindingElement>())
        {
            security.AllowInsecureTransport = true;
            foreach (var conversation in security.EndpointSupportingTokenParameters.Endorsing.OfType<SecureConversationSecurityTokenParameters>())
            {
                conversation.BootstrapSecurityBindingElement.AllowInsecureTransport = true;
            }
        }

        var https = elements.Find<HttpsTransportBindingElement>();
        elements[elements.IndexOf(https)] = new HttpTransportBindingElement
        {
            HostNameComparisonMode = HostNameComparisonMode.Exact,
            MaxReceivedMessageSize = https.MaxReceivedMessageSize,
        };
        var binding = new CustomBinding(elements) { Name = "wsHttp_TransportWithMessageCredential_offloaded" };
        host.AddServiceEndpoint(contract, binding, new Uri($"https://localhost:{HttpsPort}/{path}"), new Uri($"http://localhost:{HttpPort}/{path}"));
        Pin(host, client);
        return host;
    }

    /// <summary>The client certificate, trusted by its thumbprint: no trust store.</summary>
    private static void Pin(ServiceHost host, X509Certificate2 client)
    {
        host.Credentials.ClientCertificate.Authentication.CertificateValidationMode = X509CertificateValidationMode.Custom;
        host.Credentials.ClientCertificate.Authentication.CustomCertificateValidator = new PinnedThumbprint(client.Thumbprint);
        host.Credentials.ClientCertificate.Authentication.RevocationMode = X509RevocationMode.NoCheck;
    }
}

internal sealed class PinnedThumbprint : X509CertificateValidator
{
    private readonly string _thumbprint;

    public PinnedThumbprint(string thumbprint) => _thumbprint = thumbprint;

    public override void Validate(X509Certificate2 certificate)
    {
        if (!string.Equals(certificate.Thumbprint, _thumbprint, StringComparison.OrdinalIgnoreCase))
        {
            throw new SecurityTokenValidationException($"client certificate {certificate.Thumbprint} is not the pinned {_thumbprint}");
        }
    }
}

/// <summary>localhost:https → localhost:http: TLS with the server certificate from its file, then the bytes as they are.
/// With a pinned client certificate, TLS requires the client to present exactly that one.</summary>
internal sealed class TlsTerminator : IDisposable
{
    private readonly TcpListener _listener;

    private TlsTerminator(TcpListener listener) => _listener = listener;

    public static TlsTerminator Start(int httpsPort, int httpPort, X509Certificate2 certificate, X509Certificate2 pinnedClient)
    {
        var listener = new TcpListener(IPAddress.Loopback, httpsPort);
        listener.Start();
        var terminator = new TlsTerminator(listener);
        Task.Run(async () =>
        {
            while (true)
            {
                TcpClient inbound;
                try { inbound = await listener.AcceptTcpClientAsync(); }
                catch (ObjectDisposedException) { return; }
                catch (SocketException) { return; }
                _ = Task.Run(() => Serve(inbound, httpPort, certificate, pinnedClient));
            }
        });
        return terminator;
    }

    private static async Task Serve(TcpClient inbound, int httpPort, X509Certificate2 certificate, X509Certificate2 pinnedClient)
    {
        RemoteCertificateValidationCallback pin = (sender, presented, chain, errors) =>
            pinnedClient is null || (presented is not null
                                     && string.Equals(new X509Certificate2(presented).Thumbprint, pinnedClient.Thumbprint, StringComparison.OrdinalIgnoreCase));
        using (inbound)
        using (var tls = new SslStream(inbound.GetStream(), false, pin))
        using (var outbound = new TcpClient())
        {
            try
            {
                await tls.AuthenticateAsServerAsync(certificate, clientCertificateRequired: pinnedClient is not null, SslProtocols.Tls12, checkCertificateRevocation: false);
                await outbound.ConnectAsync(IPAddress.Loopback, httpPort);
                var plain = outbound.GetStream();
                await Task.WhenAny(tls.CopyToAsync(plain), plain.CopyToAsync(tls));
            }
            catch (Exception error) when (error is IOException || error is AuthenticationException || error is SocketException)
            {
                Console.WriteLine($"TLS terminator: {error.GetType().Name}: {error.Message}");
            }
        }
    }

    public void Dispose() => _listener.Stop();
}
