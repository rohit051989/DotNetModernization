using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary><c>hosted_service</c>: <c>BackgroundService</c> and
/// <c>IHostedService</c> implementations.</summary>
public sealed class HostedServiceDetector : IEntryPointDetector
{
    internal static readonly IReadOnlySet<string> HostedBases =
        new HashSet<string>(StringComparer.Ordinal) { "BackgroundService", "IHostedService" };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        var registered = project.Files
            .SelectMany(f => f.Root.DescendantNodes().OfType<GenericNameSyntax>())
            .Where(g => g.Identifier.Text == "AddHostedService")
            .SelectMany(g => g.TypeArgumentList.Arguments.Select(SyntaxHelpers.RightmostTypeName))
            .OfType<string>()
            .ToHashSet(StringComparer.Ordinal);

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            if (project.ResolveBase(type, HostedBases) is not { } resolved)
            {
                continue;
            }

            var confidence = new Confidence();
            if (resolved.Via is not null)
            {
                confidence.Reduce(0.9, $"{resolved.Target} reached through in-project base {resolved.Via}");
            }

            var member = type.Syntax.Members.OfType<MethodDeclarationSyntax>()
                .FirstOrDefault(m => m.Identifier.Text is "ExecuteAsync")
                ?? type.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(m => m.Identifier.Text is "StartAsync");
            var (start, end) = member is null ? SyntaxHelpers.MemberLines(type.Syntax) : SyntaxHelpers.MemberLines(member);
            var handler = new HandlerLocation
            {
                Type = type.Name,
                Namespace = type.Namespace,
                Member = member?.Identifier.Text,
                FilePath = type.File.RelativePath,
                LineStart = start,
                LineEnd = end,
            };
            yield return new DetectedEntryPoint(
                Detected.Record(EntryPointKinds.HostedService, project, handler, confidence, authDeclared: null) with
                {
                    Hosted = new HostedDetail { ServiceBase = resolved.Target, Registered = registered.Contains(type.Name) },
                },
                Detected.Identity(type.Namespace, type.Name, handler.Member),
                null,
                null);
        }
    }
}

/// <summary>
/// <c>message_consumer</c>:
/// <list type="bullet">
/// <item>Kafka <c>IConsumer&lt;TKey, TValue&gt;</c> consuming and MSMQ
/// <c>MessageQueue.Receive</c> — one entry per consuming method, including
/// inside a hosted service;</item>
/// <item>MassTransit <c>IConsumer&lt;T&gt;.Consume</c> and NServiceBus / Rebus
/// <c>IHandleMessages&lt;T&gt;.Handle</c> (2.0.0) — one entry per message
/// type handled, which is the effective route.</item>
/// </list>
/// </summary>
public sealed class MessageConsumerDetector : IEntryPointDetector
{
    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        foreach (var entry in HandlerConsumers(context))
        {
            yield return entry;
        }

        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax))
        {
            var text = type.Syntax.ToString();
            // Kafka's IConsumer takes two type arguments; MassTransit's one.
            var kafka = type.Syntax.DescendantNodes().OfType<GenericNameSyntax>().Any(g =>
                (g.Identifier.Text == "IConsumer" && g.TypeArgumentList.Arguments.Count == 2) || g.Identifier.Text == "ConsumerBuilder");
            var msmq = text.Contains("MessageQueue", StringComparison.Ordinal);
            if (!kafka && !msmq)
            {
                continue;
            }

            var hosted = project.ResolveBase(type, HostedServiceDetector.HostedBases) is not null ? type.Name : null;
            var sources = kafka ? KafkaTopics(type) : MsmqQueues(type);

            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                var consumes = method.DescendantNodes().OfType<InvocationExpressionSyntax>().Any(i => SyntaxHelpers.InvokedName(i) switch
                {
                    "Consume" => kafka,
                    "Receive" or "BeginReceive" or "ReceiveById" or "ReceiveByCorrelationId" => msmq,
                    _ => false,
                }) || (msmq && method.DescendantNodes().OfType<AssignmentExpressionSyntax>()
                    .Any(a => a.Left is MemberAccessExpressionSyntax { Name.Identifier.Text: "ReceiveCompleted" }));
                if (!consumes)
                {
                    continue;
                }

                var confidence = new Confidence();
                if (sources.Count == 0)
                {
                    confidence.Reduce(0.8, kafka
                        ? "no topic literal passed to Subscribe in the class; topic unresolved"
                        : "no queue path literal passed to new MessageQueue in the class; queue unresolved");
                }

                var (start, end) = SyntaxHelpers.MemberLines(method);
                var handler = new HandlerLocation
                {
                    Type = type.Name,
                    Namespace = type.Namespace,
                    Member = method.Identifier.Text,
                    FilePath = type.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                var transport = kafka ? "kafka" : "msmq";
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.MessageConsumer, project, handler, confidence, authDeclared: null) with
                    {
                        Messaging = new MessagingDetail
                        {
                            Transport = transport,
                            Sources = sources,
                            SourceResolution = sources.Count > 0 ? "resolved" : "unresolved",
                            HostedService = hosted,
                        },
                    },
                    Detected.Identity(type.Namespace, type.Name, method.Identifier.Text, SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    transport,
                    null);
            }
        }
    }

    /// <summary>Classes implementing a handler interface, one entry per
    /// message type. NServiceBus and Rebus share <c>IHandleMessages&lt;T&gt;</c>:
    /// the file's using decides, else the signature (NServiceBus passes an
    /// <c>IMessageHandlerContext</c>).</summary>
    private static IEnumerable<DetectedEntryPoint> HandlerConsumers(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            foreach (var baseType in type.Syntax.BaseList?.Types ?? default)
            {
                var generic = baseType.Type switch
                {
                    GenericNameSyntax g => g,
                    QualifiedNameSyntax { Right: GenericNameSyntax g } => g,
                    _ => null,
                };
                if (generic is null || generic.TypeArgumentList.Arguments.Count != 1
                    || generic.Identifier.Text is not ("IConsumer" or "IHandleMessages"))
                {
                    continue;
                }

                var messageType = SyntaxHelpers.RightmostTypeName(generic.TypeArgumentList.Arguments[0]) ?? generic.TypeArgumentList.Arguments[0].ToString();
                var methodName = generic.Identifier.Text == "IConsumer" ? "Consume" : "Handle";
                var method = type.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(m =>
                    m.Identifier.Text == methodName
                    && m.ParameterList.Parameters.FirstOrDefault()?.Type is { } first
                    && first.ToString().Contains(messageType, StringComparison.Ordinal));

                var confidence = new Confidence();
                string transport;
                if (generic.Identifier.Text == "IConsumer")
                {
                    transport = "masstransit";
                    if (!WindowsServiceDetector.Imports(type.File, "MassTransit"))
                    {
                        confidence.Reduce(0.8, "IConsumer<T> without using MassTransit; taken as MassTransit");
                    }
                }
                else if (WindowsServiceDetector.Imports(type.File, "NServiceBus"))
                {
                    transport = "nservicebus";
                }
                else if (WindowsServiceDetector.Imports(type.File, "Rebus.Handlers"))
                {
                    transport = "rebus";
                }
                else
                {
                    var nsbSignature = method?.ParameterList.Parameters.Any(p => p.Type is not null && SyntaxHelpers.RightmostTypeName(p.Type) == "IMessageHandlerContext") == true;
                    transport = nsbSignature ? "nservicebus" : "rebus";
                    confidence.Reduce(0.8, $"IHandleMessages<T> with neither NServiceBus nor Rebus imported; taken as {transport} from the Handle signature");
                }

                var (start, end) = method is null ? SyntaxHelpers.MemberLines(type.Syntax) : SyntaxHelpers.MemberLines(method);
                var handler = new HandlerLocation
                {
                    Type = type.Name,
                    Namespace = type.Namespace,
                    Member = method?.Identifier.Text,
                    FilePath = type.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.MessageConsumer, project, handler, confidence, authDeclared: null) with
                    {
                        Messaging = new MessagingDetail
                        {
                            Transport = transport,
                            Sources = [messageType],
                            SourceResolution = "resolved",
                            HostedService = null,
                        },
                    },
                    Detected.Identity(type.Namespace, type.Name, methodName, messageType),
                    $"{transport}:{messageType}",
                    null);
            }
        }
    }

    private static IReadOnlyList<string> KafkaTopics(DeclaredType type) =>
        type.Syntax.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Where(i => SyntaxHelpers.InvokedName(i) == "Subscribe")
            .SelectMany(i => i.ArgumentList.Arguments.SelectMany(a => a.Expression.DescendantNodesAndSelf().OfType<ExpressionSyntax>()))
            .Select(SyntaxHelpers.StringValue)
            .OfType<string>()
            .Distinct()
            .OrderBy(t => t, StringComparer.Ordinal)
            .ToList();

    private static IReadOnlyList<string> MsmqQueues(DeclaredType type) =>
        type.Syntax.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
            .Where(c => SyntaxHelpers.RightmostTypeName(c.Type) == "MessageQueue")
            .Select(c => SyntaxHelpers.StringValue(c.ArgumentList?.Arguments.FirstOrDefault()?.Expression))
            .OfType<string>()
            .Distinct()
            .OrderBy(q => q, StringComparer.Ordinal)
            .ToList();
}

/// <summary><c>scheduled_job</c>: Quartz <c>IJob</c>, Hangfire recurring
/// jobs, and a <c>System.Threading.Timer</c> inside a hosted service.</summary>
public sealed class ScheduledJobDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> QuartzJob = new HashSet<string>(StringComparer.Ordinal) { "IJob" };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            // Quartz: Execute(IJobExecutionContext). The parameter type tells
            // it from any other interface that happens to be named IJob.
            if (project.ResolveBase(type, QuartzJob) is not null)
            {
                var execute = type.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(m =>
                    m.Identifier.Text == "Execute"
                    && m.ParameterList.Parameters.Any(p => p.Type is not null && SyntaxHelpers.RightmostTypeName(p.Type) == "IJobExecutionContext"));
                if (execute is not null)
                {
                    yield return Entry(project, type.File, type.Name, type.Namespace, execute, execute,
                        new ScheduleDetail { Scheduler = "quartz" }, new Confidence(), SyntaxHelpers.ParameterSignature(execute.ParameterList));
                }
            }

            // A Threading.Timer driving a hosted service.
            if (project.ResolveBase(type, HostedServiceDetector.HostedBases) is not null)
            {
                foreach (var creation in type.Syntax.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
                {
                    if (!IsThreadingTimer(creation, type.File, out var qualified))
                    {
                        continue;
                    }

                    var arguments = creation.ArgumentList?.Arguments ?? default;
                    var callback = arguments.Count > 0 ? SyntaxHelpers.Collapse(arguments[0].Expression.ToString()) : null;
                    var period = arguments.Count > 3 ? SyntaxHelpers.Collapse(arguments[3].Expression.ToString()) : null;
                    var confidence = new Confidence();
                    if (!qualified)
                    {
                        confidence.Reduce(0.8, "Timer taken as System.Threading.Timer from the file's usings; not bound");
                    }

                    var callbackMethod = type.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(m => m.Identifier.Text == callback);
                    yield return Entry(project, type.File, type.Name, type.Namespace, callbackMethod, creation,
                        new ScheduleDetail { Scheduler = "threading_timer", Expression = period },
                        confidence, callback ?? "");
                }
            }
        }

        // Hangfire: RecurringJob.AddOrUpdate(...) or a recurring job manager's.
        foreach (var file in project.Files)
        {
            foreach (var invocation in file.Root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                if (SyntaxHelpers.InvokedName(invocation) != "AddOrUpdate"
                    || SyntaxHelpers.Receiver(invocation) is not { } receiver
                    || !receiver.ToString().Contains("RecurringJob", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var arguments = invocation.ArgumentList.Arguments;
                var jobId = arguments.Count > 0 ? SyntaxHelpers.StringValue(arguments[0].Expression) : null;
                var lambda = arguments.Select(a => a.Expression).OfType<LambdaExpressionSyntax>().FirstOrDefault();
                var cron = lambda is null ? null : arguments.SkipWhile(a => a.Expression != lambda).Skip(1).FirstOrDefault();
                var target = lambda?.Body.DescendantNodesAndSelf().OfType<InvocationExpressionSyntax>().FirstOrDefault();
                var genericType = invocation.Expression is MemberAccessExpressionSyntax { Name: GenericNameSyntax g }
                    ? SyntaxHelpers.RightmostTypeName(g.TypeArgumentList.Arguments[0])
                    : null;
                var (enclosingType, enclosingNamespace, _) = SyntaxHelpers.EnclosingMember(invocation);
                var member = target is null ? null : SyntaxHelpers.InvokedName(target);
                var confidence = new Confidence();
                if (jobId is null)
                {
                    confidence.Reduce(0.9, "recurring job id is not a literal");
                }

                var (start, end) = SyntaxHelpers.Lines(invocation);
                var handler = new HandlerLocation
                {
                    Type = genericType ?? enclosingType,
                    Namespace = genericType is null ? enclosingNamespace : null,
                    Member = member,
                    FilePath = file.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.ScheduledJob, project, handler, confidence, authDeclared: null) with
                    {
                        Schedule = new ScheduleDetail
                        {
                            Scheduler = "hangfire",
                            JobId = jobId,
                            Expression = cron is null ? null : SyntaxHelpers.StringValue(cron.Expression) ?? SyntaxHelpers.Collapse(cron.Expression.ToString()),
                        },
                    },
                    Detected.Identity(handler.Namespace, handler.Type, member, jobId ?? ""),
                    jobId,
                    null);
            }
        }
    }

    private static bool IsThreadingTimer(ObjectCreationExpressionSyntax creation, ParsedFile file, out bool qualified)
    {
        var written = creation.Type.ToString();
        qualified = written is "System.Threading.Timer" or "global::System.Threading.Timer";
        if (qualified)
        {
            return true;
        }

        if (written != "Timer")
        {
            return false;
        }

        var usings = file.Root.Usings.Select(u => u.Name?.ToString()).ToHashSet(StringComparer.Ordinal);
        return !usings.Contains("System.Timers") && !usings.Contains("System.Windows.Forms");
    }

    private static DetectedEntryPoint Entry(
        ProjectSource project, ParsedFile file, string type, string? ns, MethodDeclarationSyntax? member,
        Microsoft.CodeAnalysis.SyntaxNode site, ScheduleDetail schedule, Confidence confidence, string signature)
    {
        // The handler method where one is written; the call site otherwise
        // (a timer callback that is a lambda).
        var (start, end) = member is not null ? SyntaxHelpers.MemberLines(member) : SyntaxHelpers.Lines(site);
        var memberName = member?.Identifier.Text;
        var handler = new HandlerLocation
        {
            Type = type,
            Namespace = ns,
            Member = memberName,
            FilePath = file.RelativePath,
            LineStart = start,
            LineEnd = end,
        };
        return new DetectedEntryPoint(
            Detected.Record(EntryPointKinds.ScheduledJob, project, handler, confidence, authDeclared: null) with { Schedule = schedule },
            Detected.Identity(ns, type, memberName, signature),
            schedule.Scheduler,
            null);
    }
}

/// <summary><c>console_main</c>: <c>Main</c> or top-level statements, for a
/// project with no other entry points. Run by the pipeline after every
/// other detector.</summary>
public sealed class ConsoleMainDetector : IEntryPointDetector
{
    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var file in project.Files)
        {
            var globals = file.Root.Members.OfType<GlobalStatementSyntax>().ToList();
            if (globals.Count > 0)
            {
                var (start, _) = SyntaxHelpers.Lines(globals[0]);
                var (_, end) = SyntaxHelpers.Lines(globals[^1]);
                var handler = new HandlerLocation
                {
                    Type = "Program",
                    Member = "<top-level statements>",
                    FilePath = file.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.ConsoleMain, project, handler, new Confidence(), authDeclared: null) with
                    {
                        Console = new ConsoleDetail { Form = "top_level_statements" },
                    },
                    Detected.Identity(null, "Program", "<top-level statements>"),
                    null,
                    null);
            }
        }

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax or StructDeclarationSyntax))
        {
            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                if (method.Identifier.Text != "Main" || !SyntaxHelpers.HasModifier(method, "static"))
                {
                    continue;
                }

                var (start, end) = SyntaxHelpers.MemberLines(method);
                var handler = new HandlerLocation
                {
                    Type = type.Name,
                    Namespace = type.Namespace,
                    Member = "Main",
                    FilePath = type.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.ConsoleMain, project, handler, new Confidence(), authDeclared: null) with
                    {
                        Console = new ConsoleDetail { Form = "main", StaThread = SyntaxHelpers.HasAttribute(method.AttributeLists, "STAThread") },
                    },
                    Detected.Identity(type.Namespace, type.Name, "Main", SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    null,
                    null);
            }
        }
    }
}
