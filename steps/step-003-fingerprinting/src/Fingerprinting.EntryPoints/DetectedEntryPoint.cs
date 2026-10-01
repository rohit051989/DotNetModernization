namespace Fingerprinting.EntryPoints;

/// <summary>A detector's output before the pipeline stamps the id: the
/// record (with an empty <c>EntryPointId</c>) plus the parts the id is
/// derived from — Part B3: project + kind + handler + route + verb.</summary>
public sealed record DetectedEntryPoint(EntryPointRecord Record, string HandlerIdentity, string? Route, string? Verb);

/// <summary>Everything a detector reads: the project, repository-wide
/// indexes some kinds need, and the project's conventions.</summary>
public sealed record DetectionContext(
    ProjectSource Project,
    ProjectConventions Conventions,
    WcfContractIndex WcfContracts,
    RepositoryFiles Repository)
{
    /// <summary>The project's web.config files, root and folders — for
    /// ASP.NET <c>&lt;authorization&gt;</c>.</summary>
    public IReadOnlyList<ConfigFile> ProjectConfigs =>
        Repository.Configs
            .Where(c => Project.ProjectDirectory.Length == 0
                        || c.Directory.Equals(Project.ProjectDirectory, StringComparison.OrdinalIgnoreCase)
                        || c.Directory.StartsWith(Project.ProjectDirectory + "/", StringComparison.OrdinalIgnoreCase))
            .ToList();

    /// <summary>ASP.NET authorisation for a URL path, merged with what the
    /// source declares: an attribute authorises; otherwise web.config
    /// decides; when neither says anything the entry point is not assessed.</summary>
    public (string? Text, string AuthDeclared) WebAuthorisation(AuthorisationState source, string urlPath)
    {
        var config = WebAuthorization.Evaluate(ProjectConfigs, Project.ProjectDirectory, urlPath.TrimStart('/'));
        var text = string.Join(" + ", new[] { source.Text, config?.Written }.Where(t => t is not null));
        bool? noneDeclared = source.AnyAuthorise && !source.AnyAnonymous ? false : config?.NoneDeclared;
        return (text.Length == 0 ? null : text, Analysis.AuthDeclared.From(noneDeclared));
    }
}

public interface IEntryPointDetector
{
    IEnumerable<DetectedEntryPoint> Detect(DetectionContext context);
}

internal static class Detected
{
    /// <summary>The handler identity used in the id: namespace-qualified
    /// type, member and parameter types, so two same-named classes or two
    /// overloads never collide.</summary>
    public static string Identity(string? ns, string type, string? member, string signature = "") =>
        $"{(ns is null ? "" : ns + ".")}{type}.{member ?? ""}({signature})";

    public static EntryPointRecord Record(
        string kind, ProjectSource project, HandlerLocation handler, Confidence confidence, string? authDeclared) =>
        new()
        {
            EntryPointId = "",
            Kind = kind,
            ProjectPath = project.ProjectPath,
            Handler = handler,
            Confidence = confidence.Rounded,
            ConfidenceReasons = confidence.Reasons.ToList(),
            AuthDeclared = authDeclared,
        };
}
