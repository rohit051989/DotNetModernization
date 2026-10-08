using Fingerprinting.EntryPoints.Cli;
using Fingerprinting.StepHost;

// 21-APPLICATION-FINGERPRINTING.md Part B's three hard rules — MSBuildLocator
// first, stdout guarded, invariant culture — shared with step 3's Main.
var stdout = StepBootstrap.Initialise();

return await EntryPointInventoryCli.RunAsync(args, Console.In, stdout, Console.Error);
