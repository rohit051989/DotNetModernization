using System.Diagnostics;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.Outbound;
using Fingerprinting.Outbound.Cli;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Xunit;
using Xunit.Abstractions;

namespace Fingerprinting.Tests;

/// <summary>
/// release 5: two shapes common in large repositories, each reproduced with synthetic code. (1) A mapping layer
/// copying one member name between types in many classes made value resolution exponential, enough to time
/// outbound-invocation-inventory out. (2) A request with an empty URI on a plain
/// HttpClient left an unresolved operation without a reason, and the whole artifact was discarded.
/// </summary>
public sealed class LargeRepositoryPatternTests(ITestOutputHelper output)
{
    private const string ProjectPath = "src/App/App.csproj";

    // ---------- pattern 1: copying assignments ----------

    /// <summary>
    /// A DTO and a generated entity share a member <c>Code</c>; <paramref name="n"/> - 1 service classes, one per
    /// file, copy it (<c>new Entity { Name = src.Name, Code = src.Code }</c>), and one more ends the chain from another
    /// member. An HTTP request in another class reads <c>param.Code</c> after the HttpClient's runtime base address.
    /// <paramref name="typedSource"/>: the copies' source is a parameter of type Dto (the usual shape), or a
    /// local whose type the code does not show — the case fix (d) cannot help with.
    /// </summary>
    /// <paramref name="typedParam"/>: the request reads a parameter declared as Dto (the usual shape), or a local
    /// whose type is not written.
    public static Dictionary<string, string> Mapping(
        int n, bool typedSource, string copy = "initializer", string request = "concatenation", bool typedParam = true)
    {
        var files = new Dictionary<string, string>
        {
            ["src/App/Dto.cs"] = "public class Dto { public string Code { get; set; } public string Name { get; set; } }",
            ["src/App/Data.designer.cs"] = "public partial class Entity { public string Code { get; set; } public string Name { get; set; } }",
            ["src/App/ServiceLast.cs"] = "public class ServiceLast { public Entity Map(Other src2) => new Entity { Code = src2.Other }; }",
        };
        for (var i = 1; i < n; i++)
        {
            var source = typedSource ? "Dto src" : "";
            var local = typedSource ? "" : "var src = Load(); ";
            files[$"src/App/Service{i}.cs"] = copy switch
            {
                "initializer" => $"public class Service{i} {{ public Entity Map({source}) {{ {local}return new Entity {{ Name = src.Name, Code = src.Code }}; }} }}",
                "statement" => $"public class Service{i} {{ public void Map({source}) {{ {local}var e = Make(); e.Code = src.Code; }} }}",
                _ => $"public class Service{i} {{ private static readonly Holder src = Load(); public string Code = src.Code; }}",
            };
        }

        var url = request == "concatenation"
            ? """c.BaseAddress + "/orders/" + param.Code"""
            : """$"{c.BaseAddress}/orders/{param.Code}" """;
        files["src/App/Client.cs"] = $$"""
            using System.Net.Http;
            public class Client
            {
                private readonly IHttpClientFactory _factory;
                public async System.Threading.Tasks.Task Call({{(typedParam ? "Dto param" : "")}})
                {
                    {{(typedParam ? "" : "var param = Find();")}}
                    HttpClient c = _factory.CreateClient("ORDERS");
                    await c.GetAsync({{url}});
                }
            }
            """;
        return files;
    }

    private static (ProjectSource Source, IReadOnlyList<ProjectInvocations> Results, TimeSpan Took) Detect(
        Dictionary<string, string> files, WorkLimits? limits = null)
    {
        var source = ProjectSource.FromText(ProjectPath, files);
        var clock = Stopwatch.StartNew();
        var results = OutboundPipeline.Detect(Guid.Empty, [(new OutboundInputProject(ProjectPath, Guid.Empty, null, [], []), source)],
            RepositoryConfig.FromText([]), limits: limits);
        return (source, results, clock.Elapsed);
    }

    /// <summary>The resolver's work on the request URL alone: how many evaluations it took.</summary>
    private static (ResolvedValue Value, long Calls) ResolveRequest(Dictionary<string, string> files)
    {
        var source = ProjectSource.FromText(ProjectPath, files);
        var resolver = new ValueResolver(source, SymbolIndex.Build([source]), RepositoryConfig.FromText([]));
        var request = source.Files.Single(f => f.RelativePath.EndsWith("Client.cs", StringComparison.Ordinal)).Root
            .DescendantNodes().OfType<InvocationExpressionSyntax>().Single(i => i.ToString().StartsWith("c.GetAsync", StringComparison.Ordinal));
        var value = resolver.Resolve(request.ArgumentList.Arguments[0].Expression, CallSiteEvaluator.Empty);
        return (value, resolver.Calls);
    }

    [Theory]
    [InlineData(true, true, "initializer", "concatenation")]
    [InlineData(false, false, "initializer", "concatenation")]
    [InlineData(false, false, "initializer", "interpolation")]
    [InlineData(false, false, "statement", "concatenation")]
    [InlineData(false, false, "field", "concatenation")]
    public void Sixteen_copying_assignments_take_milliseconds(bool typed, bool typedSource, string copy, string request)
    {
        var (_, results, took) = Detect(Mapping(16, typedSource, copy, request, typedParam: typed));
        output.WriteLine($"{copy}, {request}, types written {typed}: {took.TotalMilliseconds:0} ms");
        Assert.True(took < TimeSpan.FromSeconds(5), $"took {took}");
        Assert.DoesNotContain(results.Single().Warnings, w => w.Code == WarningCodes.NotChecked);
    }

    [Theory]
    [InlineData(4)]
    [InlineData(5)]
    public void The_resolver_does_a_bounded_amount_of_work(int n)
    {
        // No written types anywhere: fix (d) cannot help, so this measures (a) to (c).
        var (value, calls) = ResolveRequest(Mapping(n, typedSource: false, typedParam: false));
        long before;
        using (ValueResolver.WithoutSafeguards())
        {
            before = ResolveRequest(Mapping(n, typedSource: false, typedParam: false)).Calls;
        }

        output.WriteLine($"N = {n}: {calls} resolver calls; {before} as before release 5");
        Assert.True(value.HasUnresolvableBase);   // the URL starts with the runtime base address: unusable either way
        Assert.True(calls <= 10, $"{calls} calls");
        Assert.True(before > 1_000, $"{before} calls before the fixes");
    }

    [Fact]
    public void Copies_between_members_of_one_name_add_no_value_of_their_own()
    {
        // Settings.Url is set once; Client.Url and a DTO's Url copy it. Reading any of them is that one value.
        var source = ProjectSource.FromText(ProjectPath, new Dictionary<string, string>
        {
            ["src/App/Settings.cs"] = """public class Settings { public string Url { get; set; } = "https://orders.example/api"; }""",
            ["src/App/A.cs"] = "public class A { public void Copy() { var x = Make(); var y = Other(); x.Url = y.Url; } }",
            ["src/App/B.cs"] = "public class B { public Client Build() { var s = Load(); return new Client { Url = s.Url }; } }",
            ["src/App/Use.cs"] = "public class Use { public string Get() { var any = Find(); return any.Url; } }",
        });
        var resolver = new ValueResolver(source, SymbolIndex.Build([source]), RepositoryConfig.FromText([]));
        var read = source.Files.Single(f => f.RelativePath.EndsWith("Use.cs", StringComparison.Ordinal)).Root
            .DescendantNodes().OfType<MemberAccessExpressionSyntax>().Single();
        Assert.Equal("https://orders.example/api", resolver.Resolve(read, CallSiteEvaluator.Empty).TextValue);
    }

    [Fact]
    public void A_name_assigned_in_more_than_eight_places_is_unresolved_with_the_reason()
    {
        var files = Enumerable.Range(1, 9).ToDictionary(i => $"src/App/S{i}.cs", i => $$"""public class S{{i}} { public object M() => new Target { Url = "https://h{{i}}.example" }; }""");
        files["src/App/Use.cs"] = "public class Use { public string Get() { var any = Find(); return any.Url; } }";
        var source = ProjectSource.FromText(ProjectPath, files);
        var resolver = new ValueResolver(source, SymbolIndex.Build([source]), RepositoryConfig.FromText([]));
        var read = source.Files.Single(f => f.RelativePath.EndsWith("Use.cs", StringComparison.Ordinal)).Root
            .DescendantNodes().OfType<MemberAccessExpressionSyntax>().Single();
        var value = resolver.Resolve(read, CallSiteEvaluator.Empty);
        Assert.Null(value.TextValue);
        Assert.Equal("Url is assigned in 9 places; more than 8 are not weighed", value.Reason);
        Assert.True(resolver.Calls < 5);
    }

    [Fact]
    public void A_member_read_on_a_typed_receiver_weighs_only_that_types_assignments()
    {
        // Fix (d): a DTO's Url and an entity's Url are different members. Before release 5 the two differing values
        // made the read unresolved; now the parameter's declared type picks the DTO's.
        var source = ProjectSource.FromText(ProjectPath, new Dictionary<string, string>
        {
            ["src/App/Make.cs"] = """
                public class Make
                {
                    public Dto D() => new Dto { Url = "https://dto.example/api" };
                    public Entity E() => new Entity { Url = "https://entity.example/api" };
                }
                """,
            ["src/App/Use.cs"] = "public class Use { public string Get(Dto param) => param.Url; }",
        });
        var resolver = new ValueResolver(source, SymbolIndex.Build([source]), RepositoryConfig.FromText([]));
        var read = source.Files.Single(f => f.RelativePath.EndsWith("Use.cs", StringComparison.Ordinal)).Root
            .DescendantNodes().OfType<MemberAccessExpressionSyntax>().Single();
        Assert.Equal("https://dto.example/api", resolver.Resolve(read, CallSiteEvaluator.Empty).TextValue);
    }

    // ---------- time limits inside one long computation ----------

    [Fact]
    public void A_project_limit_stops_one_long_resolution_and_the_step_carries_on()
    {
        // Pattern 1 in its usual shape, with the resolver as before release 5: many minutes. A 1 s project
        // limit stops it inside the resolver's recursion, and the other project is analysed as usual.
        var slow = ProjectSource.FromText(ProjectPath, Mapping(16, typedSource: true));
        const string otherPath = "src/Other/Other.csproj";
        var other = ProjectSource.FromText(otherPath, new Dictionary<string, string>
        {
            ["src/Other/Call.cs"] = """
                using System.Net.Http;
                public class Call { private readonly HttpClient _http = new HttpClient(); public System.Threading.Tasks.Task Go() => _http.GetAsync("https://catalog.example/items"); }
                """,
        });
        var clock = Stopwatch.StartNew();
        IReadOnlyList<ProjectInvocations> results;
        using (ValueResolver.WithoutSafeguards())
        {
            results = OutboundPipeline.Detect(Guid.Empty,
                [(new OutboundInputProject(ProjectPath, Guid.Empty, null, [], []), slow), (new OutboundInputProject(otherPath, Guid.Empty, null, [], []), other)],
                RepositoryConfig.FromText([]), limits: new WorkLimits(TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(60)));
        }

        output.WriteLine($"stopped and carried on in {clock.Elapsed.TotalSeconds:0.0} s");
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(30), $"took {clock.Elapsed}");
        var stopped = results.Single(r => r.ProjectPath == ProjectPath);
        Assert.Equal(ProjectScanStatuses.Failed, stopped.Status);
        Assert.Contains(stopped.Warnings, w => w.Code == WarningCodes.NotChecked && w.Message.Contains("took longer than 1 s"));
        Assert.Single(results.Single(r => r.ProjectPath == otherPath).Invocations);
    }

    // ---------- pattern 2: a request to the base address itself ----------

    private static InvokedOperation Operation(string client, string call)
    {
        var results = Conformance.Checked(Detect(new Dictionary<string, string>
        {
            ["src/App/Sender.cs"] = $$"""
                using System;
                using System.Net.Http;
                public class Sender
                {
                    private readonly string _u;
                    public async System.Threading.Tasks.Task Send(HttpContent content)
                    {
                        var h = {{client}};
                        await h.{{call}};
                    }
                }
                """,
        }).Results);
        return results.Single().Invocations.Single().Operations.Single();
    }

    [Fact]
    public void An_empty_request_uri_goes_to_an_unreadable_base_address_and_says_so()
    {
        var operation = Operation("new HttpClient { BaseAddress = new Uri(_u), Timeout = TimeSpan.FromSeconds(30) }", "PostAsync(\"\", content)");
        Assert.Equal(("POST", "PostAsync", "/", Resolutions.Unresolved), (operation.Verb, operation.Member, operation.Path, operation.Resolution));
        Assert.Equal("the request goes to the client's base address itself, which is not readable from the code", operation.Reason);
    }

    [Theory]
    [InlineData("PostAsync(\"\", content)", "POST")]
    [InlineData("GetAsync(\"?page=2\")", "GET")]
    [InlineData("GetAsync(\"#top\")", "GET")]
    public void A_request_to_a_literal_base_address_itself_is_its_path(string call, string verb)
    {
        var operation = Operation("new HttpClient { BaseAddress = new Uri(\"https://api.example/v1/\") }", call);
        Assert.Equal((verb, "/v1/", Resolutions.Resolved), (operation.Verb, operation.Path, operation.Resolution));
        Assert.Null(operation.Reason);
    }

    [Fact]
    public void A_record_that_does_not_conform_is_left_out_as_not_checked_and_the_rest_is_written()
    {
        var results = Detect(new Dictionary<string, string>
        {
            ["src/App/Calls.cs"] = """
                using System.Net.Http;
                public class Calls
                {
                    private readonly HttpClient _a = new HttpClient();
                    public System.Threading.Tasks.Task One() => _a.GetAsync("https://one.example/x");
                    public System.Threading.Tasks.Task Two() => _a.GetAsync("https://two.example/y");
                }
                """,
        }).Results;
        var project = results.Single();
        Assert.Equal(2, project.Invocations.Count);
        // Break one record the way the client's artifact was broken: unresolved, and no reason.
        var broken = project.Invocations[0] with
        {
            Operations = [project.Invocations[0].Operations[0] with { Resolution = Resolutions.Unresolved, Reason = null }],
        };
        var artifact = new OutboundInventoryArtifact
        {
            ScannerVersion = OutboundPipeline.ScannerVersion, RepositoryId = Guid.Empty, RepositorySlug = "fixture", SkipSource = "application-fingerprint",
            Summary = OutboundPipeline.Summarise(results),
            Projects = [project with { Invocations = [broken, project.Invocations[1]] }],
        };
        Assert.NotEmpty(OutboundInventoryCli.Problems(artifact));

        using var progress = StepProgress.Silent();
        var conformed = OutboundInventoryCli.Conform(artifact, progress);

        Assert.Empty(OutboundInventoryCli.Problems(conformed));
        var kept = conformed.Projects.Single();
        Assert.Equal([project.Invocations[1].InvocationId], kept.Invocations.Select(i => i.InvocationId));
        var warning = Assert.Single(kept.Warnings, w => w.Code == WarningCodes.NotChecked);
        Assert.Contains(broken.InvocationId, warning.Message);
        Assert.Contains("/operations/0/reason: type", warning.Message);
        Assert.Equal(1, conformed.Summary.InvocationCount);
        Assert.Contains(progress.NotCheckedItems, n => n.Path == $"{ProjectPath}#{broken.InvocationId}");
    }

    // ---------- resume never repeats a stall ----------

    [Fact]
    public void A_resume_does_not_retry_what_a_stopped_run_was_stuck_on_or_recorded_not_checked()
    {
        var folder = Path.Combine(Path.GetTempPath(), "fp-skip-" + Guid.NewGuid().ToString("N")[..8]);
        try
        {
            var first = ProjectCheckpoints.Open(folder, "k");
            first.MarkNotChecked("src/Slow/Slow.csproj", "not checked: loading the project took longer than 300 s");
            // What the last heartbeat of a stopped run left: one project stuck for 1 800 s, one just begun.
            File.WriteAllText(Path.Combine(folder, "inflight.json"),
                """[{"path":"src/Stuck/Stuck.csproj","seconds":1800},{"path":"src/Fresh/Fresh.csproj","seconds":3}]""");

            var resumed = ProjectCheckpoints.Open(folder, "k");
            Assert.True(resumed.Skipped("src/Slow/Slow.csproj", out var slow));
            Assert.StartsWith("not checked: loading", slow);
            Assert.True(resumed.Skipped("src/Stuck/Stuck.csproj", out var stuck));
            Assert.Contains("still being analysed after 1800 s", stuck);
            Assert.False(resumed.Skipped("src/Fresh/Fresh.csproj", out _));

            // And a third run still does not retry them; a person retries by removing skip.json.
            Assert.True(ProjectCheckpoints.Open(folder, "k").Skipped("src/Stuck/Stuck.csproj", out _));
            File.Delete(Path.Combine(folder, "skip.json"));
            Assert.False(ProjectCheckpoints.Open(folder, "k").Skipped("src/Stuck/Stuck.csproj", out _));
        }
        finally
        {
            if (Directory.Exists(folder))
            {
                Directory.Delete(folder, recursive: true);
            }
        }
    }

    [Fact]
    public async Task A_resumed_outbound_run_records_the_skipped_project_and_analyses_the_rest()
    {
        var root = Path.Combine(Path.GetTempPath(), "fp-resume-" + Guid.NewGuid().ToString("N")[..8]);
        try
        {
            foreach (var (path, text) in new[]
                     {
                         ("A/A.csproj", "<Project />"), ("A/Call.cs", """using System.Net.Http; class C { HttpClient h = new HttpClient(); System.Threading.Tasks.Task G() => h.GetAsync("https://a.example/x"); }"""),
                         ("B/B.csproj", "<Project />"), ("B/Call.cs", """using System.Net.Http; class D { HttpClient h = new HttpClient(); System.Threading.Tasks.Task G() => h.GetAsync("https://b.example/y"); }"""),
                     })
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Path.Combine(root, path))!);
                File.WriteAllText(Path.Combine(root, path), text);
            }

            var folder = Path.Combine(root, ".checkpoints");
            ProjectCheckpoints.Open(folder, "k");
            File.WriteAllText(Path.Combine(folder, "inflight.json"), """[{"path":"B/B.csproj","seconds":900}]""");

            using var progress = StepProgress.Silent();
            var artifact = await new OutboundPipeline().RunAsync(
                new OutboundInput(Guid.Empty, "fixture", "application-fingerprint",
                    [new OutboundInputProject("A/A.csproj", Guid.Empty, null, [], []), new OutboundInputProject("B/B.csproj", Guid.Empty, null, [], [])], []),
                root, CancellationToken.None, progress, checkpoints: ProjectCheckpoints.Open(folder, "k"));

            Assert.Single(artifact.Projects.Single(p => p.ProjectPath == "A/A.csproj").Invocations);
            var b = artifact.Projects.Single(p => p.ProjectPath == "B/B.csproj");
            Assert.Equal(ProjectScanStatuses.Failed, b.Status);
            Assert.Contains(b.Warnings, w => w.Code == WarningCodes.NotChecked && w.Message.Contains("not retried"));
            Assert.Empty(OutboundInventoryCli.Problems(artifact));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }
}
