using Fingerprinting.Outbound.Cli;
using Fingerprinting.StepHost;

// 21-STEP-003-FINGERPRINTING.md Part B's three hard rules — MSBuildLocator
// first, stdout guarded, invariant culture — shared with steps 3 and 4.
var stdout = StepBootstrap.Initialise();

return await OutboundInventoryCli.RunAsync(args, Console.In, stdout, Console.Error);
