namespace Fingerprinting.Outbound;

/// <summary>
/// Part C6: each invocation's Linux-compatibility verdict, with its reasons,
/// and a verdict on each environment binding. The invocation's verdict is
/// the worst environment's — a summary; the per-environment verdict is the
/// answer for a migration target, since an OpenShift environment
/// (appsettings.DEVOCP.json) already on SQL authentication is compatible
/// even where a legacy Windows environment is not.
/// <c>unknown</c> is given where a fact the verdict depends on is
/// unresolved — a SOAP binding that could not be evaluated, a database's
/// authentication, a Kafka SASL mechanism nothing states. An HTTP, gRPC,
/// cache or secret store call is portable whatever its endpoint, so an
/// unresolved endpoint alone does not make it unknown.
/// </summary>
public static class LinuxVerdicts
{
    /// <summary>Stamps a verdict on every environment binding and on the
    /// invocation. A SOAP client's comes from the platform matrix in
    /// <paramref name="soap"/> (1.5.0), never a rule here.</summary>
    public static Invocation Apply(Invocation invocation, SoapMatrices? soap = null)
    {
        var perEnvironment = invocation.Mechanism switch
        {
            Mechanisms.Database => (Func<EnvironmentBinding, (string, string)>)(b => Database(invocation, b.Authentication ?? invocation.Database!.Authentication, b.Host)),
            Mechanisms.MessageProducer or Mechanisms.MessageConsumer when invocation.Messaging!.Transport == "kafka" =>
                b => Kafka(b.Authentication ?? invocation.Messaging.Authentication),
            _ => null,
        };

        LinuxCompatibility summary;
        IReadOnlyList<EnvironmentBinding> bindings;
        if (invocation.Mechanism == Mechanisms.SoapClient && invocation.EnvironmentBindings.Count > 0)
        {
            // 1.4.0: each environment on its own binding and security; 1.5.0: by the platform matrix.
            var results = invocation.EnvironmentBindings.Select(b => (Binding: b, Result: SoapPlatform(b.Soap ?? Security(invocation.Soap!), soap))).ToList();
            bindings = results.Select(r => r.Binding with
            {
                LinuxVerdict = r.Result.Verdict, LinuxReasons = r.Result.Reasons, PlatformMatrixEntry = r.Result.Entry,
            }).ToList();
            var worst = results.Min(r => Verdicts.Rank(r.Result.Verdict));
            var differ = results.Select(r => string.Join("|", r.Result.Reasons)).Distinct().Count() > 1;
            summary = new LinuxCompatibility
            {
                Verdict = results.First(r => Verdicts.Rank(r.Result.Verdict) == worst).Result.Verdict,
                Reasons = results.SelectMany(r => r.Result.Reasons.Select(reason => differ ? $"{r.Binding.Environment}: {reason}" : reason)).Distinct().ToList(),
            };
        }
        else if (perEnvironment is not null && invocation.EnvironmentBindings.Count > 0)
        {
            var results = invocation.EnvironmentBindings.Select(b => (Binding: b, Result: perEnvironment(b))).ToList();
            bindings = results.Select(r => r.Binding with { LinuxVerdict = r.Result.Item1, LinuxReasons = [r.Result.Item2] }).ToList();
            var worst = results.Min(r => Verdicts.Rank(r.Result.Item1));
            var prefix = results.Count > 1;
            summary = new LinuxCompatibility
            {
                Verdict = results.First(r => Verdicts.Rank(r.Result.Item1) == worst).Result.Item1,
                Reasons = results.Select(r => prefix ? $"{r.Binding.Environment}: {r.Result.Item2}" : r.Result.Item2).Distinct().ToList(),
            };
        }
        else
        {
            summary = Summary(invocation, soap);
            bindings = invocation.EnvironmentBindings.Select(b => b with { LinuxVerdict = summary.Verdict, LinuxReasons = summary.Reasons }).ToList();
        }

        (bindings, summary) = UnqualifiedHosts(invocation, bindings, summary);

        if (invocation.Usage == Usages.Unused)
        {
            summary = summary with { Reasons = [.. summary.Reasons, "unused: no construction site and no configuration — not a dependency"] };
        }

        return invocation with { EnvironmentBindings = bindings, LinuxCompatibility = summary };
    }

    /// <summary>
    /// 1.3.0: an endpoint URL on a single-label host (<c>appsrv0341</c>) is at
    /// least <c>requires_change</c> in that environment — it resolves in a pod
    /// only if the cluster's DNS search domains cover it. URL endpoints only
    /// (SOAP, HTTP, gRPC): a database or cache host of one label is commonly a
    /// cluster service name.
    /// </summary>
    private static (IReadOnlyList<EnvironmentBinding>, LinuxCompatibility) UnqualifiedHosts(
        Invocation invocation, IReadOnlyList<EnvironmentBinding> bindings, LinuxCompatibility summary)
    {
        if (invocation.Mechanism is not (Mechanisms.SoapClient or Mechanisms.HttpClient or Mechanisms.GrpcClient))
        {
            return (bindings, summary);
        }

        static (string, IReadOnlyList<string>) Worsen(string verdict, IReadOnlyList<string> reasons, string host) =>
            (Verdicts.Rank(verdict) > Verdicts.Rank(Verdicts.RequiresChange) ? Verdicts.RequiresChange : verdict,
             [.. reasons, string.Format(Fingerprinting.Analysis.Hostnames.Reason, host)]);

        var updated = bindings.Select(b =>
        {
            if (!Fingerprinting.Analysis.Hostnames.IsUnqualified(b.Host))
            {
                return b;
            }

            var (verdict, reasons) = Worsen(b.LinuxVerdict ?? summary.Verdict, b.LinuxReasons, b.Host!);
            return b with { LinuxVerdict = verdict, LinuxReasons = reasons };
        }).ToList();

        var hosts = updated.Where(b => Fingerprinting.Analysis.Hostnames.IsUnqualified(b.Host)).Select(b => (b.Environment, Host: b.Host!))
            .Concat(Fingerprinting.Analysis.Hostnames.IsUnqualified(invocation.Endpoint.Host) ? [("default", invocation.Endpoint.Host!)] : [])
            .DistinctBy(x => (x.Environment, x.Host)).ToList();
        if (hosts.Count == 0)
        {
            return (updated, summary);
        }

        var verdict = Verdicts.Rank(summary.Verdict) > Verdicts.Rank(Verdicts.RequiresChange) ? Verdicts.RequiresChange : summary.Verdict;
        var reasons = summary.Reasons.Concat(hosts.Select(h => $"{h.Environment}: {string.Format(Fingerprinting.Analysis.Hostnames.Reason, h.Host)}"))
            .Distinct(StringComparer.Ordinal).ToList();
        return (updated, summary with { Verdict = verdict, Reasons = reasons });
    }

    private static LinuxCompatibility Summary(Invocation invocation, SoapMatrices? soap)
    {
        var (verdict, reasons) = invocation.Mechanism switch
        {
            Mechanisms.SoapClient => SoapSummary(invocation, soap),
            Mechanisms.Database => One(Database(invocation, invocation.Database!.Authentication, invocation.Endpoint.Host)),
            Mechanisms.MessageProducer or Mechanisms.MessageConsumer => invocation.Messaging!.Transport == "msmq"
                ? (Verdicts.Incompatible, ["MSMQ is Windows-only"])
                : One(Kafka(invocation.Messaging.Authentication)),
            Mechanisms.FileShare => (Verdicts.RequiresChange, ["UNC file share: needs an SMB mount or a persistent volume"]),
            Mechanisms.Ldap => Ldap(invocation.Ldap!),
            Mechanisms.Smtp or Mechanisms.HttpClient or Mechanisms.GrpcClient => Portable(invocation, Label(invocation.Mechanism)),
            Mechanisms.Cache => Portable(invocation, "Redis"),
            Mechanisms.SecretStore => Portable(invocation, invocation.SecretStore!.Provider == "vault" ? "Vault" : "Azure Key Vault"),
            _ => (Verdicts.Unknown, new List<string> { "mechanism not assessed" }),
        };
        return new LinuxCompatibility { Verdict = verdict, Reasons = reasons };
    }

    private static (string, List<string>) One((string Verdict, string Reason) result) => (result.Verdict, [result.Reason]);

    private static string Label(string mechanism) => mechanism switch
    {
        Mechanisms.HttpClient => "HTTP",
        Mechanisms.GrpcClient => "gRPC",
        _ => "SMTP",
    };

    private static EnvironmentSoapSecurity Security(SoapDetail soap) => new()
    {
        Binding = soap.Binding, SecurityMode = soap.SecurityMode, ClientCredentialType = soap.ClientCredentialType, SecuritySource = soap.SecuritySource,
    };

    private static (string, List<string>) SoapSummary(Invocation invocation, SoapMatrices? soap)
    {
        var (verdict, reasons, _) = SoapPlatform(Security(invocation.Soap!), soap);
        return (verdict, reasons.ToList());
    }

    /// <summary>
    /// 1.5.0: a SOAP call's platform verdict from the WCF client platform
    /// matrix (schemas/wcf-client-platform-*.json), keyed by binding, effective
    /// security mode and credential type — declared, or the binding's
    /// default. The flat rule it replaces said netTcpBinding was incompatible
    /// on Linux; netTcp works cross-platform, and what needs configuration is
    /// its default Windows credential, which negotiates Kerberos.
    /// </summary>
    public static (string Verdict, IReadOnlyList<string> Reasons, string? Entry) SoapPlatform(EnvironmentSoapSecurity security, SoapMatrices? soap)
    {
        if (soap?.Platform is not { } matrix || soap.Target is not { } target)
        {
            return (Verdicts.Unknown, [soap?.Platform is null ? "no WCF client platform matrix was loaded" : "the engagement has no target framework"], null);
        }

        if (security.Binding == "unknown")
        {
            return (Verdicts.Unknown, ["binding unresolved"], null);
        }

        if (security.SecurityMode is null || security.SecurityMode.Contains('|'))
        {
            return (Verdicts.Unknown, [$"{security.Binding}: security mode unresolved"], null);
        }

        var credential = security.SecurityMode == "None" ? "None" : security.ClientCredentialType;
        if (credential is null || credential.Contains('|'))
        {
            return (Verdicts.Unknown, [$"{security.Binding} {security.SecurityMode}: client credential type unresolved"], null);
        }

        var described = $"{security.Binding}, {security.SecurityMode} security, {credential} credentials" +
                        (security.SecuritySource == "binding_default" ? " (the binding's default: nothing declared)" : "");
        var entry = matrix.Find(target, security.Binding, security.SecurityMode, credential);
        if (entry is null)
        {
            return (Verdicts.Unknown, [$"{described}: no entry in the WCF client platform matrix {matrix.MatrixVersion}"], null);
        }

        var reasons = new List<string> { $"{described}: {entry.Verdict.Replace('_', ' ')} on Linux — {entry.Basis}" };
        if (entry.Fix is not null) reasons.Add($"change: {entry.Fix.Change}");
        if (entry.Caveat is not null) reasons.Add($"caveat: {entry.Caveat}");
        if (!entry.Confirmed) reasons.Add($"matrix entry {entry.Id} not yet confirmed by a person");
        return (entry.Verdict, reasons, entry.Id);
    }

    /// <summary>One environment's database verdict.</summary>
    private static (string Verdict, string Reason) Database(Invocation invocation, string authentication, string? host)
    {
        if (invocation.Database!.Provider == "sqlite")
        {
            return (Verdicts.Compatible, "SQLite: a file database, portable");
        }

        return (authentication, host) switch
        {
            (_, "(localdb)") => (Verdicts.RequiresChange, "LocalDB is Windows-only: point at a SQL Server instance"),
            ("integrated", _) => (Verdicts.RequiresChange, "Integrated Security: needs SQL authentication or a Kerberos keytab"),
            ("credentials", _) => (Verdicts.Compatible, "SQL authentication"),
            _ when invocation.Credentials.Any(c => c.Kind == "token") => (Verdicts.Compatible, "access token authentication"),
            _ when invocation.Endpoint.Resolution == Resolutions.Unresolved && host is null => (Verdicts.Unknown, "connection string unresolved"),
            _ => (Verdicts.Unknown, "authentication not declared in the connection string"),
        };
    }

    /// <summary>One environment's Kafka verdict, from its SASL mechanism.</summary>
    private static (string Verdict, string Reason) Kafka(string mechanism) => mechanism switch
    {
        "gssapi" => (Verdicts.RequiresChange, "Kerberos keytab required (SASL/GSSAPI)"),
        "plain" or "scram" or "oauthbearer" => (Verdicts.Compatible, $"SASL/{mechanism.ToUpperInvariant()}: portable"),
        "none" => (Verdicts.Compatible, "no SASL configured (plaintext or TLS only): portable"),
        _ => (Verdicts.Unknown, "Kafka SASL mechanism not stated in code or configuration"),
    };

    private static (string, List<string>) Ldap(LdapDetail ldap) => ldap.Api switch
    {
        LdapDetector.DirectoryServices or LdapDetector.AccountManagement => (Verdicts.Incompatible, [$"{ldap.Api}: Windows ADSI, not supported on Linux"]),
        LdapDetector.Protocols => (Verdicts.Compatible, ["System.DirectoryServices.Protocols is supported on Linux (needs libldap)"]),
        _ => (Verdicts.Compatible, [$"{ldap.Api}: portable LDAP client"]),
    };

    private static (string, List<string>) Portable(Invocation invocation, string what)
    {
        var reasons = new List<string>();
        if (invocation.Credentials.Any(c => c.Kind == "windows"))
        {
            reasons.Add($"{what} with Windows integrated credentials: needs Kerberos (a keytab) on Linux");
            return (Verdicts.RequiresChange, reasons);
        }

        reasons.Add($"{what}: portable");
        if (invocation.Endpoint.Resolution == Resolutions.Unresolved)
        {
            reasons.Add("endpoint unresolved — portable whatever it is");
        }

        return (Verdicts.Compatible, reasons);
    }
}
