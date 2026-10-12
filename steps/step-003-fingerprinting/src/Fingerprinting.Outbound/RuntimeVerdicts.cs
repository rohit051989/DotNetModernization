namespace Fingerprinting.Outbound;

/// <summary>
/// 1.4.0 (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C7): will a SOAP call
/// still work after the move to the engagement's target .NET? Two questions,
/// two verdicts on every environment binding — <b>platform</b>, does it work
/// on Linux (<see cref="LinuxVerdicts"/>), and <b>runtime</b>, does the
/// target's WCF client support this binding, security mode and credential
/// type. The runtime rules are data, not code: the
/// <see cref="WcfClientSupport"/> matrix. The security evaluated is the
/// effective one — declared, or else the binding's default, so a
/// wsHttpBinding with nothing declared is evaluated as Message security
/// with Windows credentials, which is what it uses.
///
/// <c>unknown</c> where the binding or security could not be read, or the
/// matrix has no entry for it — never a guess. An entry not yet confirmed
/// by a person says so in the reasons.
/// </summary>
public static class RuntimeVerdicts
{
    public static Invocation Apply(Invocation invocation, WcfClientSupport? matrix, string? target)
    {
        if (invocation.Mechanism != Mechanisms.SoapClient || invocation.Soap is null)
        {
            return invocation;
        }

        if (matrix is null || target is null)
        {
            return invocation with
            {
                RuntimeCompatibility = new RuntimeCompatibility
                {
                    Target = target ?? "unknown", MatrixVersion = matrix?.MatrixVersion ?? "none", Verdict = RuntimeVerdictValues.Unknown,
                    Reasons = [matrix is null ? "no WCF client support matrix was loaded" : "the engagement has no target framework"],
                },
            };
        }

        var fallback = new EnvironmentSoapSecurity
        {
            Binding = invocation.Soap.Binding,
            SecurityMode = invocation.Soap.SecurityMode,
            ClientCredentialType = invocation.Soap.ClientCredentialType,
            SecuritySource = invocation.Soap.SecuritySource,
        };
        var bindings = invocation.EnvironmentBindings.Count > 0
            ? invocation.EnvironmentBindings
            : [new EnvironmentBinding { Environment = "default", SourceFile = "", KeyPath = "", Resolution = invocation.Endpoint.Resolution }];
        var judged = bindings.Select(b =>
        {
            var security = b.Soap ?? fallback;
            var (verdict, reasons, entry) = Judge(matrix, target, security);
            return (Binding: b with { Soap = security, RuntimeVerdict = verdict, RuntimeReasons = reasons, RuntimeMatrixEntry = entry }, Verdict: verdict, Reasons: reasons);
        }).ToList();

        var worst = judged.Min(j => RuntimeVerdictValues.Rank(j.Verdict));
        var prefix = judged.Select(j => string.Join("|", j.Reasons)).Distinct().Count() > 1;
        return invocation with
        {
            EnvironmentBindings = invocation.EnvironmentBindings.Count > 0 ? judged.Select(j => j.Binding).ToList() : invocation.EnvironmentBindings,
            RuntimeCompatibility = new RuntimeCompatibility
            {
                Target = target,
                MatrixVersion = matrix.MatrixVersion,
                Verdict = judged.First(j => RuntimeVerdictValues.Rank(j.Verdict) == worst).Verdict,
                Reasons = judged.SelectMany(j => j.Reasons.Select(r => prefix ? $"{j.Binding.Environment}: {r}" : r)).Distinct().ToList(),
            },
        };
    }

    private static (string Verdict, IReadOnlyList<string> Reasons, string? Entry) Judge(WcfClientSupport matrix, string target, EnvironmentSoapSecurity security)
    {
        if (!matrix.HasTarget(target))
        {
            return (RuntimeVerdictValues.Unknown, [$"the WCF client support matrix {matrix.MatrixVersion} has no entries for {target}"], null);
        }

        if (security.Binding == "unknown")
        {
            return (RuntimeVerdictValues.Unknown, ["binding unresolved"], null);
        }

        if (security.SecurityMode is null || security.SecurityMode.Contains('|'))
        {
            return (RuntimeVerdictValues.Unknown, [$"{security.Binding}: security mode unresolved ({security.SecurityMode ?? "not declared, no known default"})"], null);
        }

        var credential = security.SecurityMode == "None" ? "None" : security.ClientCredentialType;
        if (credential is null || credential.Contains('|'))
        {
            return (RuntimeVerdictValues.Unknown, [$"{security.Binding} {security.SecurityMode}: client credential type unresolved"], null);
        }

        var described = $"{security.Binding}, {security.SecurityMode} security, {credential} credentials" +
                        (security.SecuritySource == "binding_default" ? " (the binding's default: nothing declared)" : "");
        var entry = matrix.Find(target, security.Binding, security.SecurityMode, credential);
        if (entry is null)
        {
            return (RuntimeVerdictValues.Unknown, [$"{described}: no entry in the WCF client support matrix {matrix.MatrixVersion} for {target}"], null);
        }

        var reasons = new List<string> { $"{described}: {entry.Verdict.Replace('_', ' ')} on {target} — {entry.Basis}" };
        if (entry.Caveat is not null) reasons.Add($"caveat: {entry.Caveat}");
        if (!entry.Confirmed) reasons.Add($"matrix entry {entry.Id} not yet confirmed by a person");
        return (entry.Verdict, reasons, entry.Id);
    }
}
