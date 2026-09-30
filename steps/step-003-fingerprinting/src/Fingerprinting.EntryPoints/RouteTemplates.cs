using System.Text.RegularExpressions;

namespace Fingerprinting.EntryPoints;

/// <summary>HTTP route composition — 29-STEPS-004-005-INVENTORIES.md Part B2.
/// Pure string rules, no syntax.</summary>
public static partial class RouteTemplates
{
    [GeneratedRegex(@"\[(controller|action|area)\]", RegexOptions.IgnoreCase)]
    private static partial Regex Token();

    /// <summary>True when an action template starts with <c>/</c> or
    /// <c>~/</c>: it replaces the controller template instead of appending.</summary>
    public static bool IsOverride(string? actionTemplate) =>
        actionTemplate is not null && (actionTemplate.StartsWith("~/", StringComparison.Ordinal) || actionTemplate.StartsWith('/'));

    /// <summary>Composes a controller template with an action template.
    /// Either may be null. The result has no leading slash; null only when
    /// both are null (nothing attribute-routed at all).</summary>
    public static string? Combine(string? controllerTemplate, string? actionTemplate)
    {
        if (IsOverride(actionTemplate))
        {
            return Trim(actionTemplate);
        }

        if (controllerTemplate is null && actionTemplate is null)
        {
            return null;
        }

        var parts = new[] { Trim(controllerTemplate), Trim(actionTemplate) }.Where(p => p.Length > 0);
        return string.Join('/', parts);
    }

    /// <summary>MapGroup prefixes, outermost first, joined with the mapped
    /// template.</summary>
    public static string JoinSegments(IEnumerable<string> segments) =>
        string.Join('/', segments.Select(Trim).Where(s => s.Length > 0));

    /// <summary><c>[controller]</c> is the class name minus a
    /// <c>Controller</c> suffix, lowercased per the default convention.</summary>
    public static string ControllerTokenValue(string className) =>
        (className.EndsWith("Controller", StringComparison.Ordinal) && className.Length > "Controller".Length
            ? className[..^"Controller".Length]
            : className).ToLowerInvariant();

    /// <summary>Resolves <c>[controller]</c>, <c>[action]</c> and
    /// <c>[area]</c>. A token that cannot be resolved (<c>[area]</c> with no
    /// <c>[Area]</c> attribute) is left in place and reported. Every
    /// resolution is reported too: it is convention, not something read.</summary>
    public static string ResolveTokens(
        string template, string controllerClassName, string actionName, string? area, Confidence confidence)
    {
        return Token().Replace(template, match =>
        {
            switch (match.Groups[1].Value.ToLowerInvariant())
            {
                case "controller":
                    var controller = ControllerTokenValue(controllerClassName);
                    confidence.Reduce(0.9, $"route token [controller] resolved by convention to '{controller}'");
                    return controller;
                case "action":
                    confidence.Reduce(0.9, $"route token [action] resolved to the action name '{actionName}'");
                    if (actionName.EndsWith("Async", StringComparison.Ordinal) && actionName.Length > "Async".Length)
                    {
                        confidence.Reduce(0.8,
                            $"action '{actionName}' ends in Async: ASP.NET Core drops the suffix by default " +
                            "(SuppressAsyncSuffixInActionNames), so the live route may lack it");
                    }

                    return actionName;
                default:
                    if (area is null)
                    {
                        confidence.Reduce(0.5, "route token [area] has no [Area] attribute to resolve it; left unresolved");
                        return match.Value;
                    }

                    confidence.Reduce(0.9, $"route token [area] resolved from [Area(\"{area}\")]");
                    return area;
            }
        });
    }

    /// <summary>Route parameter names in a template: <c>{id:int}</c> and
    /// <c>{**slug}</c> yield <c>id</c> and <c>slug</c>.</summary>
    public static IReadOnlySet<string> ParameterNames(string? template)
    {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (template is null)
        {
            return names;
        }

        foreach (Match match in RouteParameter().Matches(template))
        {
            names.Add(match.Groups[1].Value);
        }

        return names;
    }

    [GeneratedRegex(@"\{\**([A-Za-z_][A-Za-z0-9_]*)")]
    private static partial Regex RouteParameter();

    private static string Trim(string? template)
    {
        if (template is null)
        {
            return "";
        }

        var trimmed = template.StartsWith("~/", StringComparison.Ordinal) ? template[2..] : template;
        return trimmed.Trim('/');
    }
}

/// <summary>Confidence below 1.0 always carries its reason (Part A2). The
/// lowest factor wins; reasons keep the order they were found in.</summary>
public sealed class Confidence
{
    private readonly List<string> _reasons = [];

    public double Value { get; private set; } = 1.0;

    public IReadOnlyList<string> Reasons => _reasons;

    public Confidence Reduce(double value, string reason)
    {
        Value = Math.Min(Value, value);
        if (!_reasons.Contains(reason))
        {
            _reasons.Add(reason);
        }

        return this;
    }

    public Confidence Copy()
    {
        var copy = new Confidence { Value = Value };
        copy._reasons.AddRange(_reasons);
        return copy;
    }

    public double Rounded => Math.Round(Value, 2);
}
