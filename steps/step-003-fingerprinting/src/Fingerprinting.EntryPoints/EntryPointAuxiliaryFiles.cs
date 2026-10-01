namespace Fingerprinting.EntryPoints;

/// <summary>The non-C# files entry points are declared in: .svc, .proto,
/// .ashx, Global.asax, Razor Pages (.cshtml with <c>@page</c>), routable
/// Blazor components (.razor with <c>@page</c>) and WPF App.xaml.</summary>
public sealed class EntryPointAuxiliaryFiles : IAuxiliaryFiles
{
    public static EntryPointAuxiliaryFiles Instance { get; } = new();

    public bool IsCandidate(string path) =>
        path.EndsWith(".svc", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".proto", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".ashx", StringComparison.OrdinalIgnoreCase)
        || Path.GetFileName(path).Equals("Global.asax", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".cshtml", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".razor", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".xaml", StringComparison.OrdinalIgnoreCase);

    public bool Keep(string path, string text)
    {
        // Only pages, routable components and the application definition —
        // not every view, partial, layout or window.
        if (path.EndsWith(".cshtml", StringComparison.OrdinalIgnoreCase))
        {
            return RazorPageDetector.PageDirective(text) is not null;
        }

        if (path.EndsWith(".razor", StringComparison.OrdinalIgnoreCase))
        {
            return BlazorComponentDetector.Routes(text).Count > 0;
        }

        if (path.EndsWith(".xaml", StringComparison.OrdinalIgnoreCase))
        {
            return DesktopAppDetector.IsApplicationXaml(text);
        }

        return true;
    }
}
