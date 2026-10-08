using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Microsoft.CodeAnalysis;

namespace Fingerprinting.TestCoverage;

public sealed record TestCoverageInput(
    Guid RepositoryId, string RepositorySlug, string? CommitSha, IReadOnlyList<InputProject> Projects,
    IReadOnlyList<string> CoverageLocations, IReadOnlyList<Warning> Warnings);

/// <param name="TestSignals">Step 3's test signals on this project
/// (FACT_ATTRIBUTE, XUNIT_PACKAGE, ...): Part B1 reuses them.</param>
public sealed record InputProject(string ProjectPath, IReadOnlyList<string> Packages, IReadOnlyCollection<string> TestSignals);

/// <summary>
/// Lifecycle step 8, phase 1 — 32-STEP-008-TEST-COVERAGE.md Part L: test
/// discovery and classification (B), mapping (C), buckets (D), existing
/// coverage reports (E), CI maturity (H). No LLM, no test execution.
/// </summary>
public static class TestCoveragePipeline
{
    public const string ArtifactVersion = "1.0.0";

    private static readonly string[] TestPackagePrefixes = ["xunit", "nunit", "mstest", "microsoft.net.test.sdk"];

    private const string NoReportReason = "not measured — no coverage report in the repository or a configured CI output location, and test execution is not enabled";
    private const string NoUnitReportReason = "not measured — no unit coverage report, and test execution is not enabled";
    private const string IntegrationReason = "not measured — integration tests are not executed during discovery, and no integration coverage report exists";
    private const string NotInReportReason = "not measured — this file is in no coverage report";
    private const string NothingToTestReason = "not measured — no testable logic";

    public static async Task<TestCoverageArtifact> RunAsync(TestCoverageInput input, string repositoryRoot, CancellationToken ct)
    {
        var warnings = new List<Warning>(input.Warnings);
        var projects = input.Projects.Where(p => p.ProjectPath.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase))
            .OrderBy(p => p.ProjectPath, StringComparer.Ordinal).ToList();

        // Each source file belongs to the deepest project directory holding it.
        var directories = projects.ToDictionary(p => p.ProjectPath, p => DirectoryOf(p.ProjectPath));
        var filesByProject = projects.ToDictionary(p => p.ProjectPath, _ => new List<SourceFileScanner.SourceFile>());
        foreach (var project in projects)
        {
            var scan = SourceFileScanner.EnumerateCSharpFiles(repositoryRoot, Path.Combine(repositoryRoot, directories[project.ProjectPath]), ct);
            if (scan.Truncated)
            {
                warnings.Add(new Warning { Code = WarningCodes.SourceFileCapExceeded, Message = $"{project.ProjectPath}: more than {SourceFileScanner.MaxFilesPerProject} source files; analysis stopped at the cap.", Severity = WarningSeverities.Warning });
            }

            foreach (var file in scan.Files)
            {
                var owner = projects.Where(p => IsUnder(file.RelativePath, directories[p.ProjectPath]))
                    .OrderByDescending(p => directories[p.ProjectPath].Length).First();
                if (owner.ProjectPath == project.ProjectPath) filesByProject[project.ProjectPath].Add(file);
            }
        }

        var roots = new Dictionary<string, SyntaxNode>(StringComparer.Ordinal);
        foreach (var file in filesByProject.Values.SelectMany(f => f))
        {
            roots[file.RelativePath] = await SourceFileScanner.ParseAsync(file.AbsolutePath, ct);
        }

        // B1: which projects are test projects.
        var testReasons = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var project in projects)
        {
            var package = project.Packages.Where(p => TestPackagePrefixes.Any(prefix => p.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)))
                .Order(StringComparer.OrdinalIgnoreCase).FirstOrDefault();
            var signal = project.TestSignals.Order(StringComparer.Ordinal).FirstOrDefault();
            if (package is not null) testReasons[project.ProjectPath] = $"test package {package}";
            else if (signal is not null) testReasons[project.ProjectPath] = $"step 3 signal {signal}";
        }

        // C: the production types, from every file outside test projects.
        var analyses = new Dictionary<string, TestableLogic.FileAnalysis>(StringComparer.Ordinal);
        var productionTypes = new List<TestMapper.ProductionType>();
        foreach (var (projectPath, files) in filesByProject.Where(p => !testReasons.ContainsKey(p.Key)))
        {
            foreach (var file in files)
            {
                var analysis = TestableLogic.Analyze(roots[file.RelativePath]);
                analyses[file.RelativePath] = analysis;
                productionTypes.AddRange(analysis.Types.Select(t => new TestMapper.ProductionType(file.RelativePath, t.Name, t.QualifiedName, t.Namespace)));
            }
        }

        // B2 and C: classify each test class, then map it.
        var mapper = new TestMapper(productionTypes);
        var testClasses = new List<TestClassInfo>();
        var mappings = new List<TestMapping>();
        var testProjects = new List<TestProjectInfo>();
        foreach (var project in projects.Where(p => testReasons.ContainsKey(p.ProjectPath)))
        {
            var projectEvidence = new List<ClassificationEvidence>();
            if (TestDiscovery.ProjectNameType(project.ProjectPath) is { } named)
            {
                projectEvidence.Add(new ClassificationEvidence { Kind = "project_name", Value = Path.GetFileNameWithoutExtension(project.ProjectPath), Indicates = named.Type, Strength = "strong" });
            }

            projectEvidence.AddRange(TestDiscovery.ConfigEvidence(ConfigTexts(Path.Combine(repositoryRoot, directories[project.ProjectPath]), ct)));
            var before = testClasses.Count;
            foreach (var file in filesByProject[project.ProjectPath].OrderBy(f => f.RelativePath, StringComparer.Ordinal))
            {
                var root = roots[file.RelativePath];
                var usings = TestMapper.Usings(root);
                foreach (var discovered in TestDiscovery.FindTestClasses(root))
                {
                    var (type, reason, evidence) = TestDiscovery.Classify(discovered, projectEvidence);
                    testClasses.Add(new TestClassInfo
                    {
                        ProjectPath = project.ProjectPath, FilePath = file.RelativePath, ClassName = discovered.ClassName, Namespace = discovered.Namespace,
                        LineStart = discovered.LineStart, TestType = type, ClassificationReason = reason, Evidence = evidence, TestCount = discovered.TestMethods.Count,
                    });
                    mappings.AddRange(mapper.Map(discovered, file.RelativePath, type, usings));
                }
            }

            var mine = testClasses.Skip(before).ToList();
            testProjects.Add(new TestProjectInfo
            {
                ProjectPath = project.ProjectPath, Reason = testReasons[project.ProjectPath], TestClasses = mine.Count, TestClassesByType = TestTypeCounts.Of(mine.Select(c => c.TestType)),
            });
        }

        // E: existing reports.
        var productionFiles = analyses.Keys.Order(StringComparer.Ordinal).ToList();
        var (reports, unitLines, integrationLines, combinedLines) = ReadReports(repositoryRoot, input.CoverageLocations, productionFiles, testClasses, directories, testReasons, warnings, ct);

        // D: buckets, and per-file coverage.
        var mappingsByFile = mappings.GroupBy(m => m.SourceFile).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
        var sourceFiles = new List<SourceFileCoverage>();
        foreach (var (projectPath, files) in filesByProject.Where(p => !testReasons.ContainsKey(p.Key)))
        {
            foreach (var file in files)
            {
                var analysis = analyses[file.RelativePath];
                var mapped = mappingsByFile.GetValueOrDefault(file.RelativePath) ?? [];
                var bucket = analysis.TestableMembers == 0 ? Buckets.NoTestableLogic : mapped.Count > 0 ? Buckets.HasTests : Buckets.MissingTests;
                var combined = combinedLines.GetValueOrDefault(file.RelativePath);
                var unit = unitLines.GetValueOrDefault(file.RelativePath);
                var integration = integrationLines.GetValueOrDefault(file.RelativePath);
                sourceFiles.Add(new SourceFileCoverage
                {
                    ProjectPath = projectPath, FilePath = file.RelativePath, Bucket = bucket, TestableMembers = analysis.TestableMembers,
                    TestFiles = mapped.Select(m => m.TestFile).Distinct().Order(StringComparer.Ordinal).ToList(),
                    TestTypes = mapped.Select(m => m.TestType).Distinct().Order(StringComparer.Ordinal).ToList(),
                    CoverageSource = combined?.LinePct is not null ? CoverageSources.ExistingReport : CoverageSources.NotMeasured,
                    LinePct = combined?.LinePct, BranchPct = combined?.BranchPct,
                    NotMeasuredReason = combined?.LinePct is not null ? null
                        : bucket == Buckets.NoTestableLogic ? NothingToTestReason
                        : reports.Count == 0 ? NoReportReason : NotInReportReason,
                    UnitLinePct = unit?.LinePct,
                    UnitNotMeasuredReason = unit?.LinePct is not null ? null : reports.Any(r => r.Attribution == TestTypes.Unit) ? NotInReportReason : NoUnitReportReason,
                    IntegrationLinePct = integration?.LinePct,
                    IntegrationNotMeasuredReason = integration?.LinePct is not null ? null : reports.Any(r => r.Attribution == TestTypes.Integration) ? NotInReportReason : IntegrationReason,
                });
            }
        }

        sourceFiles = sourceFiles.OrderBy(f => f.FilePath, StringComparer.Ordinal).ToList();
        var projectRows = sourceFiles.GroupBy(f => f.ProjectPath).OrderBy(g => g.Key, StringComparer.Ordinal).Select(g =>
        {
            var paths = g.Select(f => f.FilePath).ToList();
            var unitPct = Aggregate(paths, unitLines);
            var integrationPct = Aggregate(paths, integrationLines);
            return new SourceProjectCoverage
            {
                ProjectPath = g.Key, Files = g.Count(),
                HasTests = g.Count(f => f.Bucket == Buckets.HasTests), MissingTests = g.Count(f => f.Bucket == Buckets.MissingTests), NoTestableLogic = g.Count(f => f.Bucket == Buckets.NoTestableLogic),
                UnitLinePct = unitPct, UnitNotMeasuredReason = unitPct is null ? (reports.Any(r => r.Attribution == TestTypes.Unit) ? NotInReportReason : NoUnitReportReason) : null,
                IntegrationLinePct = integrationPct, IntegrationNotMeasuredReason = integrationPct is null ? (reports.Any(r => r.Attribution == TestTypes.Integration) ? NotInReportReason : IntegrationReason) : null,
            };
        }).ToList();

        testClasses = testClasses.OrderBy(c => c.FilePath, StringComparer.Ordinal).ThenBy(c => c.ClassName, StringComparer.Ordinal).ToList();
        mappings = mappings.OrderBy(m => m.SourceFile, StringComparer.Ordinal).ThenBy(m => m.TestFile, StringComparer.Ordinal)
            .ThenBy(m => m.TestClass, StringComparer.Ordinal).ThenBy(m => m.ProductionType, StringComparer.Ordinal).ToList();

        return new TestCoverageArtifact
        {
            ArtifactVersion = ArtifactVersion,
            RepositoryId = input.RepositoryId,
            RepositorySlug = input.RepositorySlug,
            CommitSha = input.CommitSha,
            Summary = new TestCoverageSummary
            {
                TestProjects = testProjects.Count, TestClasses = testClasses.Count, TestMethods = testClasses.Sum(c => c.TestCount),
                TestClassesByType = TestTypeCounts.Of(testClasses.Select(c => c.TestType)),
                SourceFiles = sourceFiles.Count, SourceFilesByBucket = BucketCounts.Of(sourceFiles.Select(f => f.Bucket)),
                Mappings = mappings.Count, CoverageReports = reports.Count,
                SourceFilesMeasured = sourceFiles.Count(f => f.CoverageSource == CoverageSources.ExistingReport),
            },
            TestProjects = testProjects.OrderBy(p => p.ProjectPath, StringComparer.Ordinal).ToList(),
            TestClasses = testClasses,
            Mappings = mappings,
            Projects = projectRows,
            SourceFiles = sourceFiles,
            CoverageReports = reports,
            CiMaturity = CiMaturityScanner.Scan(repositoryRoot, ct),
            Warnings = warnings.OrderBy(w => w.Code, StringComparer.Ordinal).ThenBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    // ---------- coverage reports ----------

    private sealed record LineFigures(decimal? LinePct, decimal? BranchPct, int Covered, int Total);

    private static (List<CoverageReportInfo>, Dictionary<string, LineFigures>, Dictionary<string, LineFigures>, Dictionary<string, LineFigures>) ReadReports(
        string repositoryRoot, IReadOnlyList<string> locations, IReadOnlyList<string> productionFiles, IReadOnlyList<TestClassInfo> testClasses,
        IReadOnlyDictionary<string, string> directories, IReadOnlyDictionary<string, string> testReasons, List<Warning> warnings, CancellationToken ct)
    {
        var infos = new List<CoverageReportInfo>();
        var byKind = new Dictionary<string, Dictionary<string, CoverageReports.FileData>>
        {
            [TestTypes.Unit] = new(StringComparer.Ordinal), [TestTypes.Integration] = new(StringComparer.Ordinal), ["combined"] = new(StringComparer.Ordinal),
        };

        foreach (var (absolute, display) in CoverageReports.Find(repositoryRoot, locations, ct))
        {
            CoverageReports.ParsedReport? report;
            try
            {
                report = CoverageReports.Parse(absolute, display);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                warnings.Add(new Warning { Code = "COVERAGE_REPORT_UNREADABLE", Message = $"{display}: {ex.Message}", Severity = WarningSeverities.Warning });
                continue;
            }

            if (report is null) continue;
            var (attribution, why) = Attribute(display, testClasses, directories, testReasons);
            var unmatched = new List<string>();
            var matched = 0;
            foreach (var (reportPath, data) in report.FilesByReportPath)
            {
                var file = CoverageReports.MatchToRepository(reportPath, productionFiles);
                if (file is null)
                {
                    unmatched.Add(reportPath);
                    continue;
                }

                matched++;
                Merge(byKind["combined"], file, data);
                if (attribution is TestTypes.Unit or TestTypes.Integration) Merge(byKind[attribution], file, data);
            }

            infos.Add(new CoverageReportInfo
            {
                Path = display, Format = report.Format, Attribution = attribution, AttributionReason = why,
                FilesInReport = report.FilesByReportPath.Count, FilesMatched = matched, UnmatchedPaths = unmatched.Order(StringComparer.Ordinal).Take(50).ToList(),
            });
        }

        return (infos, Figures(byKind[TestTypes.Unit]), Figures(byKind[TestTypes.Integration]), Figures(byKind["combined"]));
    }

    /// <summary>Whose tests a report measures: the test project it sits in,
    /// when every class there is of one kind; else its name; else
    /// unattributed — it then counts only toward the combined figure.</summary>
    private static (string, string) Attribute(string display, IReadOnlyList<TestClassInfo> testClasses,
        IReadOnlyDictionary<string, string> directories, IReadOnlyDictionary<string, string> testReasons)
    {
        var owner = testReasons.Keys.Where(p => directories[p].Length > 0 && IsUnder(display, directories[p]))
            .OrderByDescending(p => directories[p].Length).FirstOrDefault();
        if (owner is not null)
        {
            var types = testClasses.Where(c => c.ProjectPath == owner).Select(c => c.TestType).Distinct().ToList();
            if (types.Count > 0 && types.All(t => t == TestTypes.Unit)) return (TestTypes.Unit, $"in {owner}, whose test classes are all unit");
            if (types.Count > 0 && types.All(TestTypes.ReachesRealSystems)) return (TestTypes.Integration, $"in {owner}, whose test classes are all integration, functional or smoke");
        }

        var name = display.ToLowerInvariant();
        if (name.Contains("unit")) return (TestTypes.Unit, "its path names unit tests");
        if (name.Contains("integration") || name.Contains("functional") || name.Contains("e2e")) return (TestTypes.Integration, "its path names integration or functional tests");
        return ("unattributed", "neither its location nor its name says which tests produced it: counted toward the combined figure only");
    }

    private static void Merge(Dictionary<string, CoverageReports.FileData> into, string file, CoverageReports.FileData data)
    {
        if (!into.TryGetValue(file, out var target)) into[file] = target = new CoverageReports.FileData();
        foreach (var (line, covered) in data.Lines) target.AddLine(line, covered);
        foreach (var (line, (covered, total)) in data.Branches)
        {
            // The same branch in two reports: keep the better-covered count, not the sum.
            var (c, t) = target.Branches.TryGetValue(line, out var was) ? was : (0, 0);
            target.Branches[line] = (Math.Max(c, covered), Math.Max(t, total));
        }
    }

    private static Dictionary<string, LineFigures> Figures(Dictionary<string, CoverageReports.FileData> data) =>
        data.ToDictionary(kv => kv.Key, kv =>
        {
            var total = kv.Value.Lines.Count;
            var covered = kv.Value.Lines.Count(l => l.Value);
            var branchTotal = kv.Value.Branches.Values.Sum(b => b.Total);
            var branchCovered = kv.Value.Branches.Values.Sum(b => b.Covered);
            return new LineFigures(Pct(covered, total), Pct(branchCovered, branchTotal), covered, total);
        }, StringComparer.Ordinal);

    private static decimal? Aggregate(IEnumerable<string> files, Dictionary<string, LineFigures> figures)
    {
        var present = files.Where(figures.ContainsKey).Select(f => figures[f]).ToList();
        return present.Count == 0 ? null : Pct(present.Sum(f => f.Covered), present.Sum(f => f.Total));
    }

    private static decimal? Pct(int covered, int total) => total == 0 ? null : Math.Round(100m * covered / total, 1, MidpointRounding.AwayFromZero);

    // ---------- helpers ----------

    private static IEnumerable<string> ConfigTexts(string projectDirectory, CancellationToken ct) =>
        FileSystemWalk.EnumerateFiles(projectDirectory, ct)
            .Where(p => Path.GetFileName(p) is var n && (n.Equals("app.config", StringComparison.OrdinalIgnoreCase)
                                                          || (n.StartsWith("appsettings", StringComparison.OrdinalIgnoreCase) && n.EndsWith(".json", StringComparison.OrdinalIgnoreCase))))
            .Order(StringComparer.Ordinal)
            .Select(File.ReadAllText);

    private static string DirectoryOf(string projectPath)
    {
        var index = projectPath.Replace('\\', '/').LastIndexOf('/');
        return index < 0 ? "" : projectPath[..index].Replace('\\', '/');
    }

    private static bool IsUnder(string relativePath, string directory) =>
        directory.Length == 0 || relativePath.Replace('\\', '/').StartsWith(directory + "/", StringComparison.OrdinalIgnoreCase);
}
