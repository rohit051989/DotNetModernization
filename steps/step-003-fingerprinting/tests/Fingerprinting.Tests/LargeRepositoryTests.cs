using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.Outbound;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>release 5: very large and legacy repositories — each project's own files read once, a time limit per
/// project and per file recorded as NOT_CHECKED, and a rerun continuing from the last completed project.</summary>
public sealed class LargeRepositoryTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "fp-large-" + Guid.NewGuid().ToString("N")[..8]);

    public LargeRepositoryTests()
    {
        // Web/Web.csproj holds Modules/Shop/Shop.csproj in a subfolder, as Orchard.Web holds its modules.
        Write("Web/Web.csproj", "<Project ToolsVersion=\"15.0\" />");
        Write("Web/Global.asax.cs", "class Global { }");
        Write("Web/Modules/Shop/Shop.csproj", "<Project ToolsVersion=\"15.0\" />");
        Write("Web/Modules/Shop/Client.cs", """
            using System.Net.Http;
            class Client { System.Threading.Tasks.Task Go(HttpClient http) => http.GetAsync("https://shop.example/api"); }
            """);
        Write("Lib/Lib.csproj", "<Project ToolsVersion=\"15.0\" />");
        Write("Lib/Util.cs", "class Util { }");
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
            // A leftover in the temp folder is harmless.
        }
    }

    private void Write(string relative, string text)
    {
        var path = Path.Combine(_root, relative.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, text);
    }

    private static OutboundInput Input(params string[] projects) => new(
        Guid.Parse("11111111-2222-3333-4444-555555555555"), "fixture", "application-fingerprint",
        projects.Select(p => new OutboundInputProject(p, Guid.Empty, null, [], [])).ToList(), []);

    [Fact]
    public void A_project_folder_is_read_without_the_project_nested_in_it()
    {
        var files = FileSystemWalk.EnumerateProjectFiles(Path.Combine(_root, "Web"), CancellationToken.None)
            .Select(f => Path.GetRelativePath(_root, f).Replace('\\', '/')).Order(StringComparer.Ordinal).ToList();

        Assert.Equal(["Web/Global.asax.cs", "Web/Web.csproj"], files);
        Assert.True(FileSystemWalk.HoldsProject(Path.Combine(_root, "Web", "Modules", "Shop")));
    }

    [Fact]
    public async Task A_call_in_a_nested_project_is_found_once_under_its_own_project()
    {
        var artifact = await new OutboundPipeline().RunAsync(Input("Web/Web.csproj", "Web/Modules/Shop/Shop.csproj", "Lib/Lib.csproj"),
            _root, CancellationToken.None);

        var found = artifact.Projects.SelectMany(p => p.Invocations.Select(i => p.ProjectPath)).ToList();
        Assert.Equal(["Web/Modules/Shop/Shop.csproj"], found);
    }

    [Fact]
    public async Task A_file_over_its_time_limit_is_recorded_not_checked_and_the_step_carries_on()
    {
        using var progress = StepProgress.Silent();
        var artifact = await new OutboundPipeline().RunAsync(Input("Web/Modules/Shop/Shop.csproj", "Lib/Lib.csproj"), _root,
            CancellationToken.None, progress, new WorkLimits(TimeSpan.FromMinutes(5), TimeSpan.FromTicks(1)));

        Assert.All(artifact.Projects, p => Assert.Contains(p.Warnings, w => w.Code == WarningCodes.NotChecked));
        Assert.Contains(progress.NotCheckedItems, n => n.Path == "Web/Modules/Shop/Client.cs" && n.Reason.StartsWith("not checked"));
    }

    [Fact]
    public async Task A_project_over_its_time_limit_is_recorded_not_checked_and_the_others_are_analysed()
    {
        using var progress = StepProgress.Silent();
        var artifact = await new OutboundPipeline().RunAsync(Input("Web/Modules/Shop/Shop.csproj"), _root,
            CancellationToken.None, progress, new WorkLimits(TimeSpan.FromTicks(1), TimeSpan.FromMinutes(1)));

        var shop = Assert.Single(artifact.Projects);
        Assert.Equal(ProjectScanStatuses.Failed, shop.Status);
        Assert.Contains(shop.Warnings, w => w.Code == WarningCodes.NotChecked && w.Message.Contains("took longer than"));
    }

    [Fact]
    public async Task A_rerun_continues_from_the_completed_projects_with_the_same_result()
    {
        var folder = Path.Combine(_root, ".checkpoints");
        var input = Input("Web/Web.csproj", "Web/Modules/Shop/Shop.csproj", "Lib/Lib.csproj");
        var first = ProjectCheckpoints.Open(folder, ProjectCheckpoints.Key("outbound", "1"));
        var before = await new OutboundPipeline().RunAsync(input, _root, CancellationToken.None, checkpoints: first);
        Assert.Equal(0, first.Reused);

        // The run is interrupted before its artifact is written: the checkpoints stay, and the rerun reuses them.
        var second = ProjectCheckpoints.Open(folder, ProjectCheckpoints.Key("outbound", "1"));
        var after = await new OutboundPipeline().RunAsync(input, _root, CancellationToken.None, checkpoints: second);
        Assert.Equal(3, second.Reused);
        Assert.Equal(JsonSerializer.Serialize(before.Projects), JsonSerializer.Serialize(after.Projects));

        // Different inputs: nothing is reused.
        var changed = ProjectCheckpoints.Open(folder, ProjectCheckpoints.Key("outbound", "2"));
        Assert.False(changed.TryGet<ProjectInvocations>("Lib/Lib.csproj", out _));

        changed.Complete();
        Assert.False(Directory.Exists(folder));
    }
}
