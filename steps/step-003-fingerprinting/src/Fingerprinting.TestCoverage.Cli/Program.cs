using Fingerprinting.StepHost;
using Fingerprinting.TestCoverage.Cli;

// Stdout guarded and invariant culture, as every step; no MSBuildLocator —
// step 8 reads source syntax only and never loads MSBuild.
var stdout = StepBootstrap.Initialise(registerMsBuild: false);

return await TestCoverageCli.RunAsync(args, Console.In, stdout, Console.Error);
