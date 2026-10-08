using Fingerprinting.Domain;
using Fingerprinting.TestCoverage;
using Microsoft.CodeAnalysis.CSharp;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 8, phase 1 — 32-TEST-COVERAGE-ASSESSMENT.md: classification
/// (B), mapping (C), buckets (D), existing reports (E), CI maturity (H).</summary>
public sealed class TestCoverageTests
{
    // ---------- Part B: classification ----------

    private static TestDiscovery.DiscoveredClass OneClass(string code) =>
        Assert.Single(TestDiscovery.FindTestClasses(CSharpSyntaxTree.ParseText(code).GetRoot()));

    private static IReadOnlyList<ClassificationEvidence> NameEvidence(string projectPath) =>
        TestDiscovery.ProjectNameType(projectPath) is { } named
            ? [new ClassificationEvidence { Kind = "project_name", Value = projectPath, Indicates = named.Type, Strength = "strong" }]
            : [];

    [Theory]
    [InlineData("tests/UnitTests/UnitTests.csproj", TestTypes.Unit)]
    [InlineData("tests/IntegrationTests/IntegrationTests.csproj", TestTypes.Integration)]
    [InlineData("tests/FunctionalTests/FunctionalTests.csproj", TestTypes.Functional)]
    [InlineData("tests/PublicApiIntegrationTests/PublicApiIntegrationTests.csproj", TestTypes.Integration)]
    [InlineData("tests/Shop.Tests.Unit/Shop.Tests.Unit.csproj", TestTypes.Unit)]
    [InlineData("tests/Shop.SmokeTests/Shop.SmokeTests.csproj", TestTypes.Smoke)]
    [InlineData("tests/Shop.E2E/Shop.E2E.csproj", TestTypes.Functional)]
    public void ProjectName_IsStrongEvidence(string project, string expected)
    {
        var testClass = OneClass("class T { [Fact] public void A() {} }");
        Assert.Equal(expected, TestDiscovery.Classify(testClass, NameEvidence(project)).Type);
    }

    [Fact]
    public void NoEvidence_IsUnclassified_NeverGuessed()
    {
        var (type, reason, _) = TestDiscovery.Classify(OneClass("class T { [Fact] public void A() { Assert.True(1 == 1); } }"), NameEvidence("tests/Shop.Tests/Shop.Tests.csproj"));
        Assert.Equal(TestTypes.Unclassified, type);
        Assert.Equal("no classification evidence", reason);
    }

    [Fact]
    public void DeclaredCategory_IsStrong()
    {
        var testClass = OneClass("""[Trait("Category", "Integration")] class T { [Fact] public void A() {} }""");
        Assert.Equal(TestTypes.Integration, TestDiscovery.Classify(testClass, []).Type);
        var mstest = OneClass("""class T { [TestMethod, TestCategory("Unit")] public void A() {} }""");
        Assert.Equal(TestTypes.Unit, TestDiscovery.Classify(mstest, []).Type);
    }

    [Fact]
    public void ConflictingStrongEvidence_IsUnclassified()
    {
        var testClass = OneClass("""[Trait("Category", "Integration")] class T { [Fact] public void A() {} }""");
        var (type, reason, _) = TestDiscovery.Classify(testClass, NameEvidence("tests/UnitTests/UnitTests.csproj"));
        Assert.Equal(TestTypes.Unclassified, type);
        Assert.Contains("conflicting evidence", reason);
    }

    [Fact]
    public void MethodsDeclaringDifferentCategories_IsUnclassified()
    {
        var testClass = OneClass("""
            class T
            {
                [Fact, Trait("Category", "Unit")] public void A() {}
                [Fact, Trait("Category", "Integration")] public void B() {}
            }
            """);
        Assert.Equal(TestTypes.Unclassified, TestDiscovery.Classify(testClass, []).Type);
    }

    [Fact]
    public void DeclaredUnit_ButUsingWebApplicationFactory_IsUnclassified()
    {
        var testClass = OneClass("""
            class T : IClassFixture<WebApplicationFactory<Program>>
            {
                [Fact] public void A() {}
            }
            """);
        var (type, reason, _) = TestDiscovery.Classify(testClass, NameEvidence("tests/UnitTests/UnitTests.csproj"));
        Assert.Equal(TestTypes.Unclassified, type);
        Assert.Contains("WebApplicationFactory", reason);
    }

    [Fact]
    public void Infrastructure_WithoutStrongEvidence_IsIntegration()
    {
        var testClass = OneClass("""class T { [Fact] public void A() { var s = new TestServer(builder); } }""");
        Assert.Equal(TestTypes.Integration, TestDiscovery.Classify(testClass, []).Type);
        var withDb = OneClass("""class T { [Fact] public void A() { Open("Server=sql01;Database=Orders;"); } }""");
        Assert.Equal(TestTypes.Integration, TestDiscovery.Classify(withDb, []).Type);
    }

    [Fact]
    public void MockingOnly_IsUnit_WithSupportingEvidence_AndLocalhostIsNotARealSystem()
    {
        var testClass = OneClass("""
            class T
            {
                [Fact] public void A()
                {
                    var repo = new Mock<IOrders>();
                    var url = "http://localhost:5000/api";
                }
            }
            """);
        var (type, reason, evidence) = TestDiscovery.Classify(testClass, []);
        Assert.Equal(TestTypes.Unit, type);
        Assert.Contains("supporting", reason);
        Assert.DoesNotContain(evidence, e => e.Kind == "service_url");
    }

    [Fact]
    public void OnlyClassesWithTestMethods_AreTestClasses_AndTheirMethodsAreCounted()
    {
        var root = CSharpSyntaxTree.ParseText("""
            namespace Shop.Tests;
            public class Helpers { public void Build() {} }
            public class OrderTests
            {
                [Fact] public void A() {}
                [Theory, InlineData(1), InlineData(2)] public void B(int x) {}
                [Xunit.Fact] public void C() {}
                private void NotATest() {}
            }
            """).GetRoot();
        var found = Assert.Single(TestDiscovery.FindTestClasses(root));
        Assert.Equal(("OrderTests", "Shop.Tests", 3), (found.ClassName, found.Namespace, found.TestMethods.Count));
    }

    // ---------- Part D: testable logic ----------

    [Theory]
    [InlineData("public class Dto { public int Id { get; set; } public string Name { get; init; } = \"\"; }", 0)]
    [InlineData("public enum Colour { Red, Green }", 0)]
    [InlineData("public interface IOrders { void Add(int id); }", 0)]
    [InlineData("public record Point(int X, int Y);", 0)]
    [InlineData("public class E { private readonly int _x; public E(int x) { _x = x; } public int X => _x; }", 0)]
    [InlineData("public class E { public E(int x) { if (x < 0) throw new ArgumentException(); } }", 1)]
    [InlineData("public class C { public int Total => Items.Sum(i => i.Price); }", 1)]
    [InlineData("public class C { private int _n; public int N { get { return _n; } set { _n = value; } } }", 0)]
    [InlineData("public class C { private int _n; public int N { get => _n; set => _n = Math.Max(0, value); } }", 1)]
    [InlineData("public class C { public void Add(int x) { Items.Add(x); } public void Noop() { } }", 1)]
    [InlineData("Console.WriteLine(\"hello\");", 1)]
    public void TestableMembers(string code, int expected)
    {
        Assert.Equal(expected, TestableLogic.Analyze(CSharpSyntaxTree.ParseText(code).GetRoot()).TestableMembers);
    }

    // ---------- Part C: mapping ----------

    private static TestMapper Mapper(params (string File, string Name, string Ns)[] types) =>
        new(types.Select(t => new TestMapper.ProductionType(t.File, t.Name, t.Name, t.Ns)));

    [Fact]
    public void TypeReference_MapsToTheDeclaringFile_AndNamingRaisesConfidence()
    {
        var mapper = Mapper(("src/Shop/OrderService.cs", "OrderService", "Shop.Services"), ("src/Shop/Order.cs", "Order", "Shop.Domain"));
        var testClass = OneClass("""
            namespace Shop.Tests.Services;
            public class OrderServiceTests
            {
                private readonly Order _order = new Order();
                [Fact] public void Places() { var sut = new OrderService(); sut.Place(_order); }
            }
            """);
        var mappings = mapper.Map(testClass, "tests/Shop.Tests/Services/OrderServiceTests.cs", TestTypes.Unit, []);
        var service = Assert.Single(mappings, m => m.SourceFile == "src/Shop/OrderService.cs");
        Assert.Equal((MappingMethods.TypeReferenceAndNaming, 0.95m), (service.Method, service.Confidence));
        Assert.Equal(["Places"], service.TestMethods);
        var order = Assert.Single(mappings, m => m.SourceFile == "src/Shop/Order.cs");
        Assert.Equal((MappingMethods.TypeReference, 0.90m), (order.Method, order.Confidence));
        Assert.Equal(["Places"], order.TestMethods);   // a field: every test method
    }

    [Fact]
    public void AmbiguousName_IsResolvedByUsings_OrMappedToEveryCandidateAtLowConfidence()
    {
        var mapper = Mapper(("src/A/Order.cs", "Order", "Shop.Sales"), ("src/B/Order.cs", "Order", "Shop.Billing"));
        var testClass = OneClass("public class T { [Fact] public void A() { var o = new Order(); } }");
        var resolved = Assert.Single(mapper.Map(testClass, "tests/T.cs", TestTypes.Unit, ["Shop.Billing"]));
        Assert.Equal(("src/B/Order.cs", 0.80m), (resolved.SourceFile, resolved.Confidence));
        var ambiguous = mapper.Map(testClass, "tests/T.cs", TestTypes.Unit, []);
        Assert.Equal(2, ambiguous.Count);
        Assert.All(ambiguous, m => Assert.Equal(0.40m, m.Confidence));
    }

    [Fact]
    public void NamingAlone_GivesALowConfidenceMapping_MarkedAsSuch_AndAMemberIsNotAType()
    {
        var mapper = Mapper(("src/Shop/Basket.cs", "Basket", "Shop"));
        var testClass = OneClass("public class BasketTests { [Fact] public void A() { var n = order.Basket; } }");
        var mapping = Assert.Single(mapper.Map(testClass, "tests/BasketTests.cs", TestTypes.Unit, []));
        Assert.Equal((MappingMethods.NamingOnly, 0.30m), (mapping.Method, mapping.Confidence));
    }

    [Fact]
    public void NamespaceMirroring_IsSupportingEvidence()
    {
        // eShopOnWeb: Microsoft.eShopWeb.UnitTests.ApplicationCore.Entities.BasketTests.BasketAddItem
        var mapper = Mapper(("src/ApplicationCore/Entities/Basket.cs", "Basket", "Microsoft.eShopWeb.ApplicationCore.Entities"));
        var testClass = OneClass("""
            namespace Microsoft.eShopWeb.UnitTests.ApplicationCore.Entities.BasketTests;
            public class BasketAddItem { [Fact] public void Adds() { var b = new Basket("buyer"); } }
            """);
        var mapping = Assert.Single(mapper.Map(testClass, "tests/UnitTests/ApplicationCore/Entities/BasketTests/BasketAddItem.cs", TestTypes.Unit, []));
        Assert.Equal((MappingMethods.TypeReferenceAndNaming, 0.95m), (mapping.Method, mapping.Confidence));
        Assert.Contains(mapping.Evidence, e => e.Contains("mirrors"));
    }

    // ---------- Part E: existing reports ----------

    [Fact]
    public void Cobertura_LinesAndBranches()
    {
        using var dir = new TempDir();
        var path = dir.Write("coverage.cobertura.xml", """
            <?xml version="1.0"?>
            <coverage line-rate="0.5">
              <sources><source>C:\agent\_work\1\s\</source></sources>
              <packages><package><classes>
                <class name="Shop.Order" filename="src\Shop\Order.cs">
                  <lines>
                    <line number="10" hits="3" />
                    <line number="11" hits="0" />
                    <line number="12" hits="1" branch="True" condition-coverage="50% (1/2)" />
                    <line number="13" hits="0" />
                  </lines>
                </class>
              </classes></package></packages>
            </coverage>
            """);
        var report = CoverageReports.Parse(path, "coverage.cobertura.xml")!;
        Assert.Equal("cobertura", report.Format);
        var (reportPath, data) = Assert.Single(report.FilesByReportPath);
        Assert.Equal("src/Shop/Order.cs", CoverageReports.MatchToRepository(reportPath, ["src/Shop/Order.cs", "src/Other/Order.cs"]));
        Assert.Equal((4, 2), (data.Lines.Count, data.Lines.Count(l => l.Value)));
        Assert.Equal((1, 2), data.Branches[12]);
    }

    [Fact]
    public void OpenCover_And_Lcov()
    {
        using var dir = new TempDir();
        var opencover = dir.Write("results.opencover.xml", """
            <CoverageSession><Modules><Module>
              <Files><File uid="1" fullPath="D:\build\src\Shop\Order.cs" /></Files>
              <Classes><Class><Methods><Method>
                <FileRef uid="1" />
                <SequencePoints><SequencePoint vc="2" sl="5" el="5" /><SequencePoint vc="0" sl="6" el="6" /></SequencePoints>
                <BranchPoints><BranchPoint vc="1" sl="5" /><BranchPoint vc="0" sl="5" /></BranchPoints>
              </Method></Methods></Class></Classes>
            </Module></Modules></CoverageSession>
            """);
        var data = Assert.Single(CoverageReports.Parse(opencover, "x")!.FilesByReportPath).Value;
        Assert.Equal((2, 1), (data.Lines.Count, data.Lines.Count(l => l.Value)));
        Assert.Equal((1, 2), data.Branches[5]);

        var lcov = dir.Write("lcov.info", "TN:\nSF:/home/ci/src/Shop/Order.cs\nDA:1,1\nDA:2,0\nBRDA:1,0,0,1\nBRDA:1,0,1,-\nend_of_record\n");
        var lcovData = Assert.Single(CoverageReports.Parse(lcov, "lcov.info")!.FilesByReportPath).Value;
        Assert.Equal((2, 1), (lcovData.Lines.Count, lcovData.Lines.Count(l => l.Value)));
        Assert.Equal((1, 2), lcovData.Branches[1]);
    }

    [Fact]
    public void AReportPathMatchingTwoFilesEqually_IsUnmatched_NotGuessed()
    {
        Assert.Null(CoverageReports.MatchToRepository("/ci/Order.cs", ["src/A/Order.cs", "src/B/Order.cs"]));
        Assert.Null(CoverageReports.MatchToRepository("/ci/Elsewhere.cs", ["src/A/Order.cs"]));
    }

    // ---------- Part H: CI maturity ----------

    [Fact]
    public void CiMaturity_FromAGitHubWorkflow()
    {
        using var dir = new TempDir();
        dir.Write(".github/workflows/build.yml", """
            jobs:
              build:
                steps:
                  - run: dotnet test --collect:"XPlat Code Coverage" /p:Threshold=80
                  - uses: actions/upload-artifact@v4
                    with:
                      path: '**/coverage.cobertura.xml'
            """);
        var ci = CiMaturityScanner.Scan(dir.Root, CancellationToken.None);
        Assert.Equal((true, true, true, true, true), (ci.HasPipeline, ci.RunsTests, ci.CollectsCoverage, ci.PublishesCoverage, ci.EnforcesCoverageGate));
        Assert.Equal("github_actions", Assert.Single(ci.Pipelines).System);
        Assert.Contains(ci.Evidence, e => e.Fact == "runs_tests" && e.Line == 4);
    }

    [Fact]
    public void CiMaturity_PipelineThatBuildsOnly_AndNoPipeline()
    {
        using var dir = new TempDir();
        dir.Write("Jenkinsfile", "pipeline { stages { stage('Build') { steps { bat 'msbuild Shop.sln' } } } }");
        var ci = CiMaturityScanner.Scan(dir.Root, CancellationToken.None);
        Assert.Equal((true, false, false, false, false), (ci.HasPipeline, ci.RunsTests, ci.CollectsCoverage, ci.PublishesCoverage, ci.EnforcesCoverageGate));

        using var empty = new TempDir();
        Assert.False(CiMaturityScanner.Scan(empty.Root, CancellationToken.None).HasPipeline);
    }

    // ---------- end to end ----------

    private static async Task<TestCoverageArtifact> Run(TempDir dir) =>
        await TestCoveragePipeline.RunAsync(new TestCoverageInput(Guid.Empty, "shop", "abc", [
            new InputProject("src/Shop/Shop.csproj", [], []),
            new InputProject("tests/Shop.UnitTests/Shop.UnitTests.csproj", ["xunit"], ["FACT_ATTRIBUTE"]),
        ], [], []), dir.Root, CancellationToken.None);

    private static TempDir ShopRepository()
    {
        var dir = new TempDir();
        dir.Write("src/Shop/Shop.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />");
        dir.Write("src/Shop/Basket.cs", "namespace Shop; public class Basket { public void Add(int x) { Items.Add(x); } }");
        dir.Write("src/Shop/Untested.cs", "namespace Shop; public class Untested { public int Twice(int x) { return x * 2; } }");
        dir.Write("src/Shop/BasketDto.cs", "namespace Shop; public class BasketDto { public int Id { get; set; } }");
        dir.Write("tests/Shop.UnitTests/Shop.UnitTests.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />");
        dir.Write("tests/Shop.UnitTests/BasketTests.cs", "namespace Shop.UnitTests; public class BasketTests { [Fact] public void Adds() { new Basket().Add(1); } }");
        return dir;
    }

    [Fact]
    public async Task EveryFileInExactlyOneBucket_AndUnknownCoverageIsNeverZero()
    {
        using var dir = ShopRepository();
        var artifact = await Run(dir);
        var buckets = artifact.SourceFiles.ToDictionary(f => f.FilePath, f => f.Bucket);
        Assert.Equal(new Dictionary<string, string>
        {
            ["src/Shop/Basket.cs"] = Buckets.HasTests,
            ["src/Shop/BasketDto.cs"] = Buckets.NoTestableLogic,
            ["src/Shop/Untested.cs"] = Buckets.MissingTests,
        }, buckets);
        Assert.All(artifact.SourceFiles, f =>
        {
            Assert.Equal(CoverageSources.NotMeasured, f.CoverageSource);
            Assert.Null(f.LinePct);
            Assert.False(string.IsNullOrEmpty(f.NotMeasuredReason));
            Assert.Contains("integration tests are not executed during discovery", f.IntegrationNotMeasuredReason);
        });
        Assert.Equal(TestTypes.Unit, Assert.Single(artifact.TestClasses).TestType);
    }

    [Fact]
    public async Task AnExistingReport_GivesMeasuredPercentages_AttributedByWhereItSits()
    {
        using var dir = ShopRepository();
        dir.Write("tests/Shop.UnitTests/TestResults/coverage.cobertura.xml", """
            <coverage><packages><package><classes>
              <class filename="/ci/src/Shop/Basket.cs"><lines><line number="1" hits="1" /></lines></class>
              <class filename="/ci/src/Shop/Untested.cs"><lines><line number="1" hits="0" /><line number="2" hits="1" /></lines></class>
            </classes></package></packages></coverage>
            """);
        var artifact = await Run(dir);
        var report = Assert.Single(artifact.CoverageReports);
        Assert.Equal((TestTypes.Unit, 2), (report.Attribution, report.FilesMatched));
        var untested = artifact.SourceFiles.Single(f => f.FilePath == "src/Shop/Untested.cs");
        Assert.Equal((CoverageSources.ExistingReport, 50.0m, 50.0m), (untested.CoverageSource, untested.LinePct!.Value, untested.UnitLinePct!.Value));
        var dto = artifact.SourceFiles.Single(f => f.FilePath == "src/Shop/BasketDto.cs");
        Assert.Equal(CoverageSources.NotMeasured, dto.CoverageSource);
        Assert.Equal(66.7m, artifact.Projects.Single().UnitLinePct);
    }

    [Fact]
    public async Task TheArtifactIsDeterministic()
    {
        using var dir = ShopRepository();
        Assert.Equal(DeterministicJson.Serialize(await Run(dir)), DeterministicJson.Serialize(await Run(dir)));
    }

    /// <summary>Part I: the cache keeps the result as JSONB, which reorders
    /// object keys. A reused result must still write byte-identically.</summary>
    [Fact]
    public async Task AResultReadBackWithKeysInAnyOrder_WritesByteIdentically()
    {
        using var dir = ShopRepository();
        var json = DeterministicJson.Serialize(await Run(dir));
        var scrambled = ReverseKeys(System.Text.Json.Nodes.JsonNode.Parse(json)!).ToJsonString();
        Assert.NotEqual(System.Text.Json.Nodes.JsonNode.Parse(json)!.ToJsonString(), scrambled);   // the order really changed
        var readBack = System.Text.Json.JsonSerializer.Deserialize<TestCoverageArtifact>(scrambled, DeterministicJson.Options)!;
        Assert.Equal(json, DeterministicJson.Serialize(readBack));
    }

    private static System.Text.Json.Nodes.JsonNode ReverseKeys(System.Text.Json.Nodes.JsonNode node) => node switch
    {
        System.Text.Json.Nodes.JsonObject o => new System.Text.Json.Nodes.JsonObject(
            o.Reverse().Select(kv => KeyValuePair.Create(kv.Key, kv.Value is null ? null : ReverseKeys(kv.Value.DeepClone())))),
        System.Text.Json.Nodes.JsonArray a => new System.Text.Json.Nodes.JsonArray(a.Select(i => i is null ? null : ReverseKeys(i.DeepClone())).ToArray()),
        _ => node.DeepClone(),
    };

    private sealed class TempDir : IDisposable
    {
        public string Root { get; } = Directory.CreateTempSubdirectory("step8-").FullName;

        public string Write(string relative, string content)
        {
            var path = Path.Combine(Root, relative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, content);
            return path;
        }

        public void Dispose()
        {
            try { Directory.Delete(Root, true); } catch (IOException) { }
        }
    }
}
