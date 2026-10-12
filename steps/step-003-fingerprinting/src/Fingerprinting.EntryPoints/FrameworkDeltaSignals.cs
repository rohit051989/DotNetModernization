using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>
/// The framework delta catalog's discovery side (34-CONVERSION-ARCHITECTURE.md,
/// "Framework deltas"): known breaking changes between a project's framework
/// and a later one, each a signal, so the conversion plan can fix them before
/// the retarget and every commit stays green. They are facts about the
/// repository's structure, emitted whatever the engagement's target; the
/// delta catalog says from which framework each one breaks.
/// <list type="bullet">
/// <item><c>AMBIGUOUS_TOP_LEVEL_PROGRAM_ON_NET10</c> — from .NET 10, ASP.NET
/// Core generates <c>public partial class Program</c> for a web project whose
/// entry point is top-level statements, so a project that references two such
/// projects and names <c>Program</c> no longer compiles (CS0433). On net8.0
/// the implicit Program is internal and only an explicit
/// <c>public partial class Program</c> is visible. One signal per referenced
/// project whose Program becomes public only on net10.0; value the file
/// holding its top-level statements (where the fix goes), source the
/// consuming file that names <c>Program</c>.</item>
/// </list>
/// </summary>
public static class FrameworkDeltaSignals
{
    public const string AmbiguousTopLevelProgramOnNet10 = "AMBIGUOUS_TOP_LEVEL_PROGRAM_ON_NET10";

    private const int MaxEvidence = 20;

    /// <summary>How one project's <c>Program</c> comes about.</summary>
    public sealed record ProgramShape(string ProjectPath, string? TopLevelFile, bool ExplicitPublic, bool ExplicitInternal, bool WebSdk)
    {
        public bool PublicOnSource => TopLevelFile is not null && ExplicitPublic;

        /// <summary>The .NET 10 generator makes it public unless the project
        /// pins its accessibility with an explicit internal declaration.</summary>
        public bool PublicOnNet10 => TopLevelFile is not null && (ExplicitPublic || (WebSdk && !ExplicitInternal));
    }

    public static ProgramShape Shape(string projectPath, string? projectSdk, ProjectSource source)
    {
        string? topLevel = null;
        bool explicitPublic = false, explicitInternal = false;
        foreach (var file in source.Files.Where(f => !f.IsGenerated).OrderBy(f => f.RelativePath, StringComparer.Ordinal))
        {
            if (topLevel is null && file.Root.Members.OfType<GlobalStatementSyntax>().Any()) topLevel = file.RelativePath;
            // Program from top-level statements lives in the global namespace.
            foreach (var program in file.Root.Members.OfType<ClassDeclarationSyntax>().Where(c => c.Identifier.Text == "Program"))
            {
                explicitPublic |= program.Modifiers.Any(m => m.IsKind(SyntaxKind.PublicKeyword));
                explicitInternal |= program.Modifiers.Any(m => m.IsKind(SyntaxKind.InternalKeyword));
            }
        }

        var web = (projectSdk ?? "").Equals("Microsoft.NET.Sdk.Web", StringComparison.OrdinalIgnoreCase);
        return new ProgramShape(projectPath, topLevel, explicitPublic, explicitInternal, web);
    }

    /// <summary>By project path, the framework delta signals.
    /// <paramref name="references"/> is step 2's resolved project references
    /// (source, referenced); a project sees every project it references,
    /// transitively.</summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<Signal>> Build(
        IReadOnlyList<(string ProjectPath, string? ProjectSdk, ProjectSource Source)> projects,
        IReadOnlyList<(string Source, string Referenced)> references)
    {
        var shapes = projects.ToDictionary(p => p.ProjectPath, p => Shape(p.ProjectPath, p.ProjectSdk, p.Source), StringComparer.OrdinalIgnoreCase);
        var direct = references
            .GroupBy(r => r.Source, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.Select(r => r.Referenced).ToList(), StringComparer.OrdinalIgnoreCase);
        var signals = new Dictionary<string, IReadOnlyList<Signal>>(StringComparer.Ordinal);

        foreach (var (projectPath, _, source) in projects.OrderBy(p => p.ProjectPath, StringComparer.Ordinal))
        {
            // A project with a Program of its own binds the name to that one.
            if (shapes[projectPath].TopLevelFile is not null
                || source.Files.Any(f => f.Root.Members.OfType<ClassDeclarationSyntax>().Any(c => c.Identifier.Text == "Program")))
                continue;

            var seen = Closure(projectPath, direct).Where(shapes.ContainsKey).Select(p => shapes[p]).ToList();
            var onTarget = seen.Where(s => s.PublicOnNet10).ToList();
            if (onTarget.Count < 2 || seen.Count(s => s.PublicOnSource) > 1) continue;   // fine on net10, or already ambiguous

            var uses = Uses(source);
            if (uses.Count == 0) continue;   // never names Program: nothing to bind ambiguously

            var file = uses.First().File;
            var evidence = uses.Where(u => u.File == file).Take(MaxEvidence)
                .Select(u => new Evidence { LineStart = u.Line, LineEnd = u.Line, Member = "Program" }).ToList();
            signals[projectPath] = onTarget
                .Where(s => !s.PublicOnSource)
                .OrderBy(s => s.TopLevelFile, StringComparer.Ordinal)
                .Select(s => new Signal
                {
                    Name = AmbiguousTopLevelProgramOnNet10,
                    Category = SignalCategories.EntryPoint,
                    Type = SignalTypes.EntryPoint,
                    Value = s.TopLevelFile,
                    SourceType = EvidenceSourceTypes.SourceCode,
                    SourcePath = file,
                    EvidenceKind = SignalEvidenceKinds.File,
                    OccurrenceCount = uses.Count,
                    Evidence = evidence,
                    Extractor = ArchitectureSignals.Extractor,
                    ExtractionConfidence = 0.90m,
                })
                .ToList();
        }

        return signals;
    }

    private static IEnumerable<string> Closure(string project, IReadOnlyDictionary<string, List<string>> direct)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var queue = new Queue<string>([project]);
        while (queue.Count > 0)
        {
            foreach (var referenced in direct.GetValueOrDefault(queue.Dequeue()) ?? [])
            {
                if (seen.Add(referenced)) queue.Enqueue(referenced);
            }
        }

        return seen.Order(StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>Where the project names <c>Program</c> as a type, by syntax.</summary>
    private static List<(string File, int Line)> Uses(ProjectSource source) =>
        source.Files
            .Where(f => !f.IsGenerated)
            .OrderBy(f => f.RelativePath, StringComparer.Ordinal)
            .SelectMany(f => f.Root.DescendantNodes().OfType<IdentifierNameSyntax>()
                // x.Program is a member called Program, not the type
                .Where(n => n.Identifier.Text == "Program" && !(n.Parent is MemberAccessExpressionSyntax access && access.Name == n))
                .Select(n => (f.RelativePath, n.GetLocation().GetLineSpan().StartLinePosition.Line + 1)))
            .ToList();
}
