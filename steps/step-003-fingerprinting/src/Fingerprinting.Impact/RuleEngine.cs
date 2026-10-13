using System.Text.Json;
using System.Xml;
using System.Xml.Linq;

namespace Fingerprinting.Impact;

/// <summary>A seed file of a work item: item-detection's occurrence evidence.</summary>
public sealed record SeedFile(string Path, string? Signal, string? Value);

/// <summary>A test mapping from test-coverage-assessment (Part E, referencing_tests).</summary>
public sealed record TestLink(string SourceFile, string ProductionType, string TestFile, string TestClass, string Method, decimal Confidence);

/// <summary>An entry point from entry-point-inventory (Part E, entry_points).</summary>
public sealed record EntryPointRef(string Kind, string HandlerType, string? HandlerNamespace, string? Member, string FilePath);

/// <summary>A project hosting a WCF contract — entry-point-inventory's
/// HOSTS_WCF_SERVICE signal on the project constructing the ServiceHost or
/// holding the .svc (Part E, hosting_project).</summary>
public sealed record HostLink(string ProjectPath, string Contract);

/// <summary>A Web Deploy SetParam / SetParameters file
/// outbound-invocation-inventory found for a project, and its environment
/// (Part E, deploy_parameter_files).</summary>
public sealed record DeployFile(string ProjectPath, string File, string Environment);

/// <summary>The repository's projects: path → directory.</summary>
public sealed record ProjectMap(IReadOnlyDictionary<string, string> Directories)
{
    /// <summary>The project owning a file: the deepest project directory holding it.</summary>
    public string? Owner(string file) =>
        Directories.Where(p => p.Value.Length == 0 || file.StartsWith(p.Value + "/", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(p => p.Value.Length).Select(p => p.Key).FirstOrDefault();
}

/// <summary>
/// Evaluates one resolution's impact rules for one work item —
/// 33-IMPACT-ANALYSIS Parts D to F. Each rule starts from the seed or earlier rules,
/// applies one primitive, filters, and assigns an action. Every node carries
/// its traversal path back to the seed; certainty is confirmed through
/// resolved references and possible through a name match, an ambiguous type
/// or an unverified convention. Merged to one entry per file, strongest
/// action kept, every reason recorded.
///
/// <b>An action describes what happens to the file.</b> A config element a
/// rule reaches is part of a file, so removing or editing it updates the
/// file, with the element in the entry's details. A type whose file declares
/// other types the same rule does not delete is removed from the file, which
/// is an update, not a delete. Delete is kept for a file that goes entirely.
/// </summary>
public sealed class RuleEngine(
    CodeIndex index, ProjectMap projects, IReadOnlyList<TestLink> tests, IReadOnlyList<EntryPointRef> entryPoints,
    IReadOnlyList<HostLink>? hostLinks = null, IReadOnlyList<DeployFile>? deployFiles = null,
    VersionDeclarations? versionDeclarations = null)
{
    private IReadOnlyList<string> _packageIds = [];

    /// <summary>A file reached by a rule, with the type that brought it there.</summary>
    /// <param name="Element">Set when the rule reached part of a file (a config
    /// element), not the file: "&lt;services&gt; at system.serviceModel/services, line 30".</param>
    /// <param name="Environment">Set by deploy_parameter_files: the ASP.NET Core
    /// environment the file's values belong to ({node.environment}).</param>
    private sealed record Node(string File, CodeIndex.TypeInfo? Type, bool Confirmed, IReadOnlyList<string> Trace, string? Element = null,
        string? Environment = null)
    {
        public Node Then(string file, CodeIndex.TypeInfo? type, bool confirmed, string hop, string? element = null, string? environment = null) =>
            new(file, type, Confirmed && confirmed, [.. Trace, hop], element, environment);
    }

    public sealed record Result(IReadOnlyList<ImpactEntry> Entries, IReadOnlyList<string> KnownLimits, IReadOnlyList<string> DeferredRules);

    public Result Evaluate(IReadOnlyList<ImpactRule> rules, IReadOnlyList<SeedFile> seeds, string projectPath,
        IReadOnlyList<string>? packageIds = null)
    {
        _packageIds = packageIds ?? [];
        var outputs = new Dictionary<string, List<Node>>(StringComparer.Ordinal) { ["seed"] = SeedNodes(seeds) };
        var raw = new List<(ImpactEntry Entry, string Key)>();
        var deferred = new List<string>();
        var projectDir = projects.Directories.GetValueOrDefault(projectPath) ?? "";

        foreach (var rule in rules)
        {
            if (rule.Create is not null)
            {
                // One new file per node of for_each, or one per project where the
                // path names no type (a host's Program.cs per .svc-hosted project:
                // the merge keeps one entry per path).
                var perType = (rule.ProposedPath ?? "").Contains("{type.", StringComparison.Ordinal);
                foreach (var node in outputs.GetValueOrDefault(rule.ForEach ?? "") ?? [])
                {
                    if (perType && node.Type is null) continue;
                    var path = (rule.ProposedPath ?? "").Replace("{project.dir}", projectDir.Length == 0 ? "." : projectDir)
                        .Replace("{node.project.dir}", NodeProjectDir(node, projectDir));
                    if (node.Type is not null)
                    {
                        path = path.Replace("{type.base_name}", node.Type.BaseName).Replace("{type.name}", node.Type.Name)
                            .Replace("{type.resource}", Resource(node.Type));
                    }

                    if (path.Contains("{node.environment}", StringComparison.Ordinal))
                    {
                        if (node.Environment is null) continue;
                        path = path.Replace("{node.environment}", node.Environment);
                    }
                    var reason = new ImpactReason { RuleId = rule.Id, Action = Actions.Create, Reason = rule.Create };
                    var certainty = node.Confirmed ? Certainties.Confirmed : Certainties.Possible;
                    var trace = Render(node.Then(path, node.Type, true, perType ? $"new file for {node.Type!.Name}" : "new file"));
                    if (index.Files.Contains(path))
                    {
                        // The file the rule would create is already there: it is
                        // edited, not created, and the details say so.
                        raw.Add((new ImpactEntry
                        {
                            FilePath = index.Files.First(f => string.Equals(f, path, StringComparison.OrdinalIgnoreCase)),
                            Action = Actions.Update, Certainty = certainty, Reasons = [reason], TraversalPaths = [trace],
                            Details = [$"{rule.Create}: the proposed new file already exists, so it is updated"],
                        }, index.Files.First(f => string.Equals(f, path, StringComparison.OrdinalIgnoreCase))));
                        continue;
                    }

                    raw.Add((new ImpactEntry
                    {
                        ProposedPath = path, Description = node.Type is null || !perType ? rule.Create : $"{rule.Create}: {node.Type.Name}",
                        Action = Actions.Create, Details = [], Certainty = certainty, Reasons = [reason], TraversalPaths = [trace],
                    }, "create:" + path));
                }

                outputs[rule.Id] = [];
                continue;
            }

            if (rule.Traverse == "client_call_sites")
            {
                deferred.Add(rule.Id);   // dependency-and-context-map: integration edges
                outputs[rule.Id] = [];
                continue;
            }

            var input = rule.Sources().SelectMany(s => outputs.GetValueOrDefault(s) ?? []).ToList();
            var produced = rule.Select == "self" ? input : Traverse(rule, input, projectPath);
            produced = Filter(rule, produced);
            outputs[rule.Id] = produced;
            if (rule.Action == Actions.None) continue;   // a stepping stone for later rules: nothing happens to these files
            foreach (var node in produced)
            {
                var (action, details) = FileAction(rule.Action, node, produced);
                raw.Add((new ImpactEntry
                {
                    FilePath = node.File, Action = action, Certainty = node.Confirmed ? Certainties.Confirmed : Certainties.Possible,
                    Reasons = [new ImpactReason { RuleId = rule.Id, Action = rule.Action, Reason = rule.Reason ?? rule.Id }],
                    TraversalPaths = [Render(node)], Details = details,
                }, node.File));
            }
        }

        var merged = raw.GroupBy(r => r.Key, StringComparer.Ordinal).Select(g =>
        {
            var entries = g.Select(r => r.Entry).ToList();
            var strongest = entries.OrderByDescending(e => Actions.Strength(e.Action)).First();
            return strongest with
            {
                Certainty = entries.Any(e => e.Certainty == Certainties.Confirmed) ? Certainties.Confirmed : Certainties.Possible,
                Reasons = entries.SelectMany(e => e.Reasons).Distinct().OrderBy(r => r.RuleId, StringComparer.Ordinal).ThenBy(r => r.Reason, StringComparer.Ordinal).ToList(),
                TraversalPaths = entries.SelectMany(e => e.TraversalPaths).Distinct().Order(StringComparer.Ordinal).ToList(),
                Details = entries.SelectMany(e => e.Details).Distinct().Order(StringComparer.Ordinal).ToList(),
            };
        }).OrderBy(e => e.FilePath ?? "~" + e.ProposedPath, StringComparer.Ordinal).ToList();

        var limits = merged.Where(e => e.FilePath is not null && index.Reflection.ContainsKey(e.FilePath))
            .Select(e => $"Reflection in {e.FilePath} ({string.Join(", ", index.Reflection[e.FilePath!])}): impact through it is not traced")
            .Distinct().Order(StringComparer.Ordinal).ToList();
        return new Result(merged, limits, deferred);
    }

    /// <summary>What a rule's action means for the file the node is in. A
    /// config element: the file is updated, the element named in the details.
    /// A delete of types: the file goes only if every top-level type it
    /// declares is among those this rule deletes; otherwise those types are
    /// removed from it, an update.</summary>
    private (string Action, IReadOnlyList<string> Details) FileAction(string action, Node node, List<Node> produced)
    {
        if (node.Element is not null)
        {
            return (action == Actions.Delete ? Actions.Update : action, [$"element {node.Element}"]);
        }

        if (action != Actions.Delete || node.Type is null) return (action, []);
        var deleted = produced.Where(n => n.File == node.File && n.Type is not null).Select(n => n.Type!.FullName).ToHashSet(StringComparer.Ordinal);
        var others = index.Types.Where(t => t.File == node.File && !t.QualifiedName.Contains('.') && !deleted.Contains(t.FullName))
            .Select(t => t.Name).Distinct().Order(StringComparer.Ordinal).ToList();
        return others.Count == 0
            ? (Actions.Delete, [])
            : (Actions.Update, [$"removes {node.Type.Name}; the file also declares {string.Join(", ", others)}"]);
    }

    private List<Node> SeedNodes(IReadOnlyList<SeedFile> seeds)
    {
        var nodes = new List<Node>();
        foreach (var seed in seeds.DistinctBy(s => s.Path).OrderBy(s => s.Path, StringComparer.Ordinal))
        {
            var hop = $"evidence {seed.Path}" + (seed.Signal is null ? "" : $" ({seed.Signal}{(seed.Value is null ? "" : " " + seed.Value)})");
            var declared = index.Types.Where(t => t.File == seed.Path).ToList();
            if (declared.Count == 0) nodes.Add(new Node(seed.Path, null, true, [hop]));
            nodes.AddRange(declared.Select(t => new Node(seed.Path, t, true, [hop])));
        }

        return nodes;
    }

    private List<Node> Traverse(ImpactRule rule, List<Node> input, string projectPath) => rule.Traverse switch
    {
        "implemented_interfaces" => ByType(input, type => type.BaseNames.SelectMany(name =>
        {
            var (found, unique) = index.Resolve(name, type);
            return found.Where(f => f.Kind == "interface").Select(f => (f, unique, $"{f.Name} implemented by {type.Name}"));
        })),
        "implementations_of" => ByType(input, type => index.Types
            .Where(t => t.BaseNames.Contains(type.Name, StringComparer.Ordinal))
            .Select(t => (t, (index.TypesByName.GetValueOrDefault(type.Name)?.Count ?? 0) == 1, $"{t.Name} implementing {type.Name}"))),
        "signature_types" => ByType(input, type => type.Members.SelectMany(member => member.SignatureNames.SelectMany(name =>
        {
            var (found, unique) = index.Resolve(name, type);
            return found.Where(f => f.Name != type.Name).Select(f => (f, unique, $"{f.Name} used in {type.Name}.{member.Name}"));
        }))),
        "declaring_files" => input.Where(n => n.Type is not null).Select(n => n.Then(n.Type!.File, n.Type, true, $"file declaring {n.Type.Name}")).ToList(),
        "referencing_files" => ReferencingFiles(input),
        "config_elements" => ConfigElements(input, rule.Path ?? ""),
        "convention_files" => ConventionFiles(input, rule.Kind ?? ""),
        "referencing_tests" => ReferencingTests(input),
        "project_file" => ProjectFiles(input, projectPath),
        "version_declaration" => VersionDeclarationFiles(input, projectPath),
        "project_files" => ProjectFilesMatching(input, projectPath, rule.Pattern ?? ""),
        "hosting_project" => HostingProjects(input),
        "deploy_parameter_files" => DeployParameterFiles(input, projectPath),
        "entry_points" => EntryPoints(input),
        _ => [],
    };

    private static List<Node> ByType(List<Node> input, Func<CodeIndex.TypeInfo, IEnumerable<(CodeIndex.TypeInfo Type, bool Unique, string Hop)>> step)
    {
        var result = new List<Node>();
        foreach (var node in input.Where(n => n.Type is not null))
        {
            result.AddRange(step(node.Type!).Select(s => node.Then(s.Type.File, s.Type, s.Unique, s.Hop)));
        }

        return result;
    }

    private List<Node> ReferencingFiles(List<Node> input)
    {
        var result = new List<Node>();
        foreach (var node in input.Where(n => n.Type is not null))
        {
            var unique = (index.TypesByName.GetValueOrDefault(node.Type!.Name)?.Count ?? 0) == 1;
            foreach (var (file, names) in index.ReferencedNames.OrderBy(kv => kv.Key, StringComparer.Ordinal))
            {
                if (file != node.Type.File && names.Contains(node.Type.Name))
                {
                    result.Add(node.Then(file, null, unique, $"{file} references {node.Type.Name}"));
                }
            }
        }

        return result;
    }

    /// <summary>Config files with an element at <paramref name="path"/> that
    /// names one of the types (confirmed by full name, possible by simple
    /// name), or that sit in the project of an input file (confirmed).</summary>
    private List<Node> ConfigElements(List<Node> input, string path)
    {
        var result = new List<Node>();
        var segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
        var inputProjects = input.Select(n => projects.Owner(n.File)).Where(p => p is not null).ToHashSet();
        foreach (var config in index.Configs)
        {
            var at = ElementsAt(config.Document, segments);
            if (at.Count == 0) continue;
            var naming = false;
            foreach (var node in input.Where(n => n.Type is not null).DistinctBy(n => n.Type!.FullName))
            {
                foreach (var element in at.SelectMany(e => e.DescendantsAndSelf()))
                {
                    var values = element.Attributes().Select(a => a.Value).ToList();
                    var full = values.Any(v => v == node.Type!.FullName);
                    if (full && !index.IsNearestCopy(node.Type!, config.Path)) continue;   // another copy's config
                    var simple = !full && values.Any(v => (v == node.Type!.Name || v.EndsWith("." + node.Type!.Name, StringComparison.Ordinal))
                                                          && !index.Declares(v));
                    if (!full && !simple) continue;
                    var line = ((IXmlLineInfo)element).LineNumber;
                    result.Add(node.Then(config.Path, node.Type, full, $"<{element.Name.LocalName}> at {path} in {config.Path}:{line} names {node.Type!.Name}",
                        $"<{element.Name.LocalName}> at {path}, line {line}"));
                    naming = true;
                    break;
                }
            }

            if (!naming && inputProjects.Contains(projects.Owner(config.Path)) && input.Count > 0)
            {
                var line = ((IXmlLineInfo)at[0]).LineNumber;
                result.Add(input[0].Then(config.Path, null, true, $"<{at[0].Name.LocalName}> at {path} in {config.Path}:{line}, same project",
                    $"<{at[0].Name.LocalName}> at {path}, line {line}"));
            }
        }

        return result;
    }

    private static List<XElement> ElementsAt(XDocument document, string[] segments)
    {
        IEnumerable<XElement> current = document.Root is null ? [] : [document.Root];
        // A path is relative to <configuration>.
        foreach (var segment in segments)
        {
            current = current.SelectMany(e => e.Elements().Where(c => c.Name.LocalName.Equals(segment, StringComparison.OrdinalIgnoreCase)));
        }

        return current.ToList();
    }

    private List<Node> ConventionFiles(List<Node> input, string kind)
    {
        var result = new List<Node>();
        var typed = input.Where(n => n.Type is not null).DistinctBy(n => n.Type!.FullName).ToList();
        foreach (var file in index.Conventions.Where(c => c.Kind == kind))
        {
            foreach (var node in typed)
            {
                var type = node.Type!;
                bool full, simple;
                if (kind is "svc" or "asmx" or "webforms_markup")
                {
                    full = file.Target == type.FullName;
                    if (full && !index.IsNearestCopy(type, file.Path)) continue;   // activates another copy of the type
                    simple = !full && file.Target is not null && (file.Target == type.Name || file.Target.EndsWith("." + type.Name, StringComparison.Ordinal))
                             && !index.Declares(file.Target);
                }
                else
                {
                    // svcutil proxies and WSDL: a name in the text — a convention
                    // that cannot be verified, so possible.
                    full = false;
                    simple = file.Text.Contains(type.Name, StringComparison.Ordinal);
                }

                if (!full && !simple) continue;
                var verb = kind switch { "svc" or "asmx" => "activates", "webforms_markup" => "is the markup of", "reference" => "proxies", _ => "mentions" };
                result.Add(node.Then(file.Path, type, full, $"{file.Path} {verb} {type.Name}"));
            }
        }

        return result;
    }

    private List<Node> ReferencingTests(List<Node> input)
    {
        var result = new List<Node>();
        foreach (var node in input)
        {
            var links = tests.Where(t => node.Type is not null ? t.ProductionType == node.Type.FullName : t.SourceFile == node.File);
            foreach (var link in links)
            {
                var confirmed = link.Method.StartsWith("type_reference", StringComparison.Ordinal) && link.Confidence >= 0.8m;
                result.Add(node.Then(link.TestFile, null, confirmed,
                    $"test {link.TestClass} ({link.Method}, confidence {link.Confidence:0.00})"));
            }
        }

        return result;
    }

    /// <summary>The projects hosting the input contracts (an implementation
    /// counts through the contracts it implements), from entry-point-inventory's
    /// HOSTS_WCF_SERVICE link: one node per (host project, contract), on the
    /// host's project file, carrying the contract as its type. Only a project
    /// the link names is reached — never an arbitrary one.</summary>
    private List<Node> HostingProjects(List<Node> input)
    {
        var result = new List<Node>();
        foreach (var node in input.Where(n => n.Type is not null))
        {
            var contracts = node.Type!.Kind == "interface"
                ? [node.Type]
                : node.Type.BaseNames.SelectMany(b => index.Resolve(b, node.Type).Types).Where(t => t.Kind == "interface").ToList();
            foreach (var contract in contracts)
            {
                // The link names the contract by simple name. Where copies of one
                // codebase each host a contract of that name, this contract's host
                // is the one nearest its own file — the same rule as a .svc
                // directive (CodeIndex.IsNearestCopy).
                var links = (hostLinks ?? []).Where(l => l.Contract == contract.Name).ToList();
                var nearest = links.Count == 0 ? 0 : links.Max(l => SharedDirectories(l.ProjectPath, contract.File));
                foreach (var link in links.Where(l => SharedDirectories(l.ProjectPath, contract.File) == nearest)
                             .OrderBy(l => l.ProjectPath, StringComparer.Ordinal))
                {
                    result.Add(node.Then(link.ProjectPath, contract, links.Count == 1 || nearest > 0, $"{link.ProjectPath} hosts {contract.Name}"));
                }
            }
        }

        return result.DistinctBy(n => (n.File, n.Type!.FullName)).ToList();
    }

    /// <summary>The SetParam / SetParameters files outbound-invocation-inventory
    /// found for the input nodes' projects (the work item's own where there is
    /// none), each with its environment. A developer-machine environment
    /// (LOCAL) maps to ASP.NET Core's Development, so its appsettings
    /// counterpart is appsettings.Development.json.</summary>
    private List<Node> DeployParameterFiles(List<Node> input, string projectPath)
    {
        var owners = input.Select(n => projects.Owner(n.File)).Where(p => p is not null).Select(p => p!).ToHashSet(StringComparer.Ordinal);
        if (owners.Count == 0) owners.Add(projectPath);
        var origin = input.FirstOrDefault();
        return (deployFiles ?? []).Where(d => owners.Contains(d.ProjectPath))
            .DistinctBy(d => d.File).OrderBy(d => d.File, StringComparer.Ordinal)
            .Select(d =>
            {
                var environment = AspNetCoreEnvironment(d.Environment);
                var hop = $"{d.File}: deploy parameters of {d.ProjectPath} for {d.Environment}";
                return origin is null
                    ? new Node(d.File, null, true, [hop], null, environment)
                    : origin.Then(d.File, null, true, hop, null, environment);
            })
            .ToList();
    }

    private static int SharedDirectories(string a, string b)
    {
        var x = a.Split('/');
        var y = b.Split('/');
        var n = 0;
        while (n < x.Length - 1 && n < y.Length - 1 && string.Equals(x[n], y[n], StringComparison.OrdinalIgnoreCase)) n++;
        return n;
    }

    private static string AspNetCoreEnvironment(string environment) =>
        environment.Equals("LOCAL", StringComparison.OrdinalIgnoreCase) ? "Development" : environment;

    /// <summary>IOrderService → Orders: the contract's resource name, for a REST
    /// controller. The leading I and a trailing "Service" are dropped and the
    /// rest pluralised by simple English rules.</summary>
    private static string Resource(CodeIndex.TypeInfo type)
    {
        var stem = type.BaseName;
        if (stem.EndsWith("Service", StringComparison.Ordinal) && stem.Length > "Service".Length) stem = stem[..^"Service".Length];
        if (stem.EndsWith('y') && stem.Length > 1 && !"aeiou".Contains(char.ToLowerInvariant(stem[^2]))) return stem[..^1] + "ies";
        if (stem.EndsWith('s') || stem.EndsWith('x') || stem.EndsWith("ch", StringComparison.Ordinal) || stem.EndsWith("sh", StringComparison.Ordinal)) return stem + "es";
        return stem + "s";
    }

    /// <summary>The directory of the project owning the node's file — where a
    /// create belongs when it follows the node (a fault type beside the
    /// contracts it serves), not the work item's own project.</summary>
    private string NodeProjectDir(Node node, string fallback)
    {
        var owner = projects.Owner(node.File);
        var dir = owner is null ? fallback : projects.Directories.GetValueOrDefault(owner) ?? fallback;
        return dir.Length == 0 ? "." : dir;
    }

    /// <summary>Files in the projects of the input nodes (the work item's own
    /// project where there is none) whose path below the project directory
    /// matches <paramref name="pattern"/>: <c>*</c> within a name, <c>/</c>
    /// between directories, matched without regard to case. The files a
    /// conversion makes obsolete or edits by convention — a host's
    /// <c>App.config</c>, Web Deploy's <c>Parameters.xml</c>.</summary>
    private List<Node> ProjectFilesMatching(List<Node> input, string projectPath, string pattern)
    {
        var owners = input.Select(n => projects.Owner(n.File)).Where(p => p is not null).Select(p => p!).ToHashSet(StringComparer.Ordinal);
        if (owners.Count == 0) owners.Add(projectPath);
        var regex = new System.Text.RegularExpressions.Regex(
            "^" + System.Text.RegularExpressions.Regex.Escape(pattern).Replace("\\*", "[^/]*") + "$",
            System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        var origin = input.FirstOrDefault();
        var result = new List<Node>();
        foreach (var project in owners.Order(StringComparer.Ordinal))
        {
            var dir = projects.Directories.GetValueOrDefault(project) ?? "";
            var prefix = dir.Length == 0 ? "" : dir + "/";
            foreach (var file in index.Files.Where(f => f.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
                                                        && projects.Owner(f) == project
                                                        && regex.IsMatch(f[prefix.Length..])).Order(StringComparer.Ordinal))
            {
                var hop = $"{file} in project {project}";
                result.Add(origin is null ? new Node(file, null, true, [hop]) : origin.Then(file, null, true, hop));
            }
        }

        return result;
    }

    private List<Node> ProjectFiles(List<Node> input, string projectPath)
    {
        var owners = input.Select(n => projects.Owner(n.File)).Where(p => p is not null).Select(p => p!).ToHashSet(StringComparer.Ordinal);
        if (owners.Count == 0) owners.Add(projectPath);
        var origin = input.FirstOrDefault();
        return owners.Order(StringComparer.Ordinal)
            .Select(p => origin is null ? new Node(p, null, true, [$"project file {p}"]) : origin.Then(p, null, true, $"project file {p}"))
            .ToList();
    }

    /// <summary>version_declaration: for each package the work item names, the file where its version is
    /// declared for the owning project — the project file, Directory.Packages.props, or the props file holding the
    /// property its version names (VersionDeclarations). Where it cannot be found, the project file, possible.</summary>
    private List<Node> VersionDeclarationFiles(List<Node> input, string projectPath)
    {
        var owners = ProjectFiles(input, projectPath);
        if (versionDeclarations is null || _packageIds.Count == 0) return owners;
        var result = new List<Node>();
        foreach (var owner in owners)
        {
            foreach (var package in _packageIds)
            {
                var found = versionDeclarations.Find(owner.File, package);
                result.Add(found is null
                    ? owner.Then(owner.File, null, false, $"version of {package}: declaration not found, assumed in the project file")
                    : owner.Then(found.File, null, true, $"version of {package} declared in {found.File}", element: found.Element));
            }
        }

        return result;
    }

    private List<Node> EntryPoints(List<Node> input)
    {
        var result = new List<Node>();
        foreach (var node in input.Where(n => n.Type is not null))
        {
            foreach (var entry in entryPoints.Where(e => e.HandlerType == node.Type!.Name && (e.HandlerNamespace is null || e.HandlerNamespace == node.Type.Namespace)))
            {
                result.Add(node.Then(entry.FilePath, node.Type, true, $"{entry.Kind} {entry.Member ?? entry.HandlerType} of {node.Type!.Name}"));
            }
        }

        return result;
    }

    private List<Node> Filter(ImpactRule rule, List<Node> nodes)
    {
        if (rule.Filter is null) return nodes;
        IEnumerable<Node> kept = nodes;
        foreach (var (name, value) in rule.Filter)
        {
            var text = value.ValueKind == JsonValueKind.String ? value.GetString() : null;
            kept = name switch
            {
                "has_attribute" => kept.Where(n => n.Type is not null && n.Type.Attributes.Contains(text ?? "")),
                "in_project" => kept.Where(n => projects.Owner(n.File) == text),
                "namespace_prefix" => kept.Where(n => n.Type?.Namespace?.StartsWith(text ?? "", StringComparison.Ordinal) ?? false),
                "excludes_generated" => value.ValueKind == JsonValueKind.False ? kept : kept.Where(n => !index.GeneratedFiles.Contains(n.File)),
                // Which kind of file a rule acts on: being an item's evidence does
                // not make a file something its conversion edits the same way.
                "extension" => kept.Where(n => Extensions(value).Contains(Path.GetExtension(n.File), StringComparer.OrdinalIgnoreCase)),
                _ => kept,
            };
        }

        return kept.ToList();
    }

    private static IReadOnlyList<string> Extensions(JsonElement value) => value.ValueKind == JsonValueKind.Array
        ? value.EnumerateArray().Select(e => e.GetString() ?? "").ToList()
        : [value.GetString() ?? ""];

    /// <summary>"Account used in IAccountService.GetAccount ← IAccountService
    /// implemented by AccountService ← evidence src/…/AccountService.cs":
    /// the file first, back to the seed.</summary>
    private static string Render(Node node) => string.Join(" ← ", node.Trace.Reverse());
}
