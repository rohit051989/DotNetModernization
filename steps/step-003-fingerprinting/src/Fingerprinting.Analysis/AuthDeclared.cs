namespace Fingerprinting.Analysis;

// Shared by step 4 (who must authenticate to call in) and step 5 (whether
// a client presents credentials when it calls out).
/// <summary>
/// Whether authentication is declared for an entry point — as written in
/// source or config. Deliberately not "authorised / unauthorised": gateway,
/// reverse-proxy and header-based authentication (an API gateway such as
/// Apigee, an access manager such as ISAM injecting identity headers) sit
/// outside the code and are invisible to static analysis. So
/// <see cref="NoneDeclared"/> is a prompt to review how the entry point is
/// protected, not a finding that it is open.
/// </summary>
public static class AuthDeclared
{
    /// <summary>An attribute, convention, config rule or WCF client
    /// credential requires the caller to authenticate.</summary>
    public const string Declared = "declared";

    /// <summary>Nothing in source or config declares authentication, or
    /// something declares it waived (<c>[AllowAnonymous]</c>, a WCF endpoint
    /// taking no client credential, an anonymous Azure Function).</summary>
    public const string NoneDeclared = "none_declared";

    /// <summary>Where authentication would be declared — web.config, WCF
    /// endpoints — says nothing this step can read.</summary>
    public const string NotAssessed = "not_assessed";

    /// <summary>The note every artifact and view carries with these values.</summary>
    public const string Scope =
        "auth_declared reports authentication as declared in source and config only. Gateway, reverse-proxy and " +
        "header-based authentication (an API gateway, an access manager injecting identity headers) are not visible " +
        "to static analysis, so none_declared is a prompt to review how the entry point is protected, not a security finding.";

    /// <summary>From a three-state answer: true = none declared, false =
    /// declared, null = not assessed.</summary>
    public static string From(bool? noneDeclared) => noneDeclared switch
    {
        true => NoneDeclared,
        false => Declared,
        null => NotAssessed,
    };
}
