using System.Globalization;
using Fingerprinting.Cli;
using Microsoft.Build.Locator;

// 21-STEP-003-FINGERPRINTING.md Part B rule 3: MSBuildLocator.RegisterDefaults()
// is the first statement in Main, before any method referencing a
// Microsoft.Build type is even JIT-compiled. Fingerprinting.Analysis holds
// MSBuild usage behind an interface resolved only after this call.
if (!MSBuildLocator.IsRegistered)
{
    MSBuildLocator.RegisterDefaults();
}

// Part B rule 1: stdout is the response channel and nothing else. Swap it out
// immediately so a stray Console.WriteLine anywhere in the call tree — ours or
// a library's — lands on stderr instead of corrupting the StepResult.
var stdout = Console.Out;
Console.SetOut(Console.Error);

// Part B rule 2: invariant culture for every number and date format.
CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.InvariantCulture;

return await EntryPoint.RunAsync(args, Console.In, stdout, Console.Error);
