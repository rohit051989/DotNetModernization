using Fingerprinting.Impact.Cli;
using Fingerprinting.StepHost;

// Stdout guarded and invariant culture, as every step; no MSBuildLocator —
// impact-analysis reads source syntax only and never loads MSBuild.
var stdout = StepBootstrap.Initialise(registerMsBuild: false);

return await ImpactCli.RunAsync(Console.In, stdout, Console.Error);
