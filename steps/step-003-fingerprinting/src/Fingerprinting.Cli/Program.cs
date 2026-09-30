using Fingerprinting.Cli;
using Fingerprinting.StepHost;

// 21-STEP-003-FINGERPRINTING.md Part B's three hard rules — MSBuildLocator
// first, stdout guarded, invariant culture — as the very first statement.
// Shared with the entry-point inventory's Main.
var stdout = StepBootstrap.Initialise();

return await EntryPoint.RunAsync(args, Console.In, stdout, Console.Error);
