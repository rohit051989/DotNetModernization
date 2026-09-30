using System.Globalization;
using Microsoft.Build.Locator;

namespace Fingerprinting.StepHost;

/// <summary>
/// The ordering-sensitive start of every step exe's <c>Main</c> —
/// 21-STEP-003-FINGERPRINTING.md Part B's three hard rules. Call it as the
/// first statement, before anything else runs.
/// </summary>
public static class StepBootstrap
{
    /// <summary>Registers MSBuild, moves stray console output to stderr and
    /// fixes the culture. Returns the real stdout: the only writer the
    /// StepResult may go to.</summary>
    public static TextWriter Initialise()
    {
        // Rule 3: MSBuildLocator.RegisterDefaults() before any method
        // referencing a Microsoft.Build type is even JIT-compiled.
        // Fingerprinting.Analysis holds MSBuild usage behind an interface
        // resolved only after this call.
        if (!MSBuildLocator.IsRegistered)
        {
            MSBuildLocator.RegisterDefaults();
        }

        // Rule 1: stdout is the response channel and nothing else. Swap it
        // out immediately so a stray Console.WriteLine anywhere in the call
        // tree — ours or a library's — lands on stderr instead of corrupting
        // the StepResult.
        var stdout = Console.Out;
        Console.SetOut(Console.Error);

        // Rule 2: invariant culture for every number and date format.
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.InvariantCulture;

        return stdout;
    }
}
