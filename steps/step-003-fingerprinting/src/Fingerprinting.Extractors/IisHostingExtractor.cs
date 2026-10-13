using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Registry 1.11.0: an ASP.NET Core application hosted in IIS through the ASP.NET Core Module, and how.
/// <c>ASPNETCORE_HOSTING_MODEL</c> carries the hosting model — <c>inprocess</c>, <c>outofprocess</c> or
/// <c>unspecified</c> — from the project file's <c>&lt;AspNetCoreHostingModel&gt;</c> (which the SDK writes into the
/// published web.config) and from a web.config's <c>&lt;aspNetCore hostingModel="..."&gt;</c>, or the module handler
/// (<c>modules="AspNetCoreModule"</c> / <c>"AspNetCoreModuleV2"</c>) with no model stated. In a container nothing of
/// this applies: Kestrel serves directly. The presence of an <c>&lt;aspNetCore&gt;</c> element alone remains
/// ASPNETCORE_CONFIG (ConfigurationExtractor); UseIIS / UseIISIntegration calls are USE_IIS_INVOCATION
/// (ApiUsageExtractor).
/// </summary>
public sealed class IisHostingExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "IisHostingExtractor";
    public const string HostingModel = "ASPNETCORE_HOSTING_MODEL";

    private static readonly Regex ProjectHostingModel =
        new(@"<AspNetCoreHostingModel>\s*(?<model>[A-Za-z]+)\s*</AspNetCoreHostingModel>", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public string Name => ExtractorName;

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var projectFile = Path.Combine(context.RepositoryRoot, context.ProjectRelativePath.Replace('/', Path.DirectorySeparatorChar));
        if (File.Exists(projectFile))
        {
            var text = File.ReadAllText(projectFile);
            if (ProjectHostingModel.Match(text) is { Success: true } m)
            {
                Add(accumulator, Normalise(m.Groups["model"].Value), context.ProjectRelativePath.Replace('\\', '/'),
                    text.AsSpan(0, m.Index).Count('\n') + 1);
            }
        }

        foreach (var file in Directory.EnumerateFiles(context.ProjectDirectory, "web*.config", SearchOption.TopDirectoryOnly))
        {
            cancellationToken.ThrowIfCancellationRequested();
            XDocument document;
            try
            {
                document = XDocument.Load(file, LoadOptions.SetLineInfo);
            }
            catch (Exception ex) when (ex is XmlException or IOException)
            {
                continue;
            }

            var relative = FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, file);
            var aspNetCore = document.Descendants().FirstOrDefault(e => e.Name.LocalName == "aspNetCore");
            var handler = document.Descendants().FirstOrDefault(e => e.Name.LocalName == "add"
                && ((string?)e.Attribute("modules"))?.StartsWith("AspNetCoreModule", StringComparison.OrdinalIgnoreCase) == true);
            var element = aspNetCore ?? handler;
            if (element is null) continue;
            var model = (string?)aspNetCore?.Attribute("hostingModel");
            Add(accumulator, model is null ? "unspecified" : Normalise(model), relative, ((IXmlLineInfo)element).LineNumber);
        }

        return Task.FromResult(new ExtractorResult { Signals = accumulator.Build(), Warnings = [] });
    }

    private static string Normalise(string model) => model.Replace("-", "").ToLowerInvariant() switch
    {
        "inprocess" => "inprocess",
        "outofprocess" => "outofprocess",
        _ => "unspecified",
    };

    private static void Add(SignalAccumulator accumulator, string model, string sourcePath, int line) =>
        accumulator.Add(HostingModel, SignalCategories.HostingIndicator, SignalTypes.ConfigElement, model,
            EvidenceSourceTypes.Configuration, sourcePath, ExtractorName,
            evidence: new Evidence { LineStart = line, LineEnd = line });
}
