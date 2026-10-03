using Fingerprinting.Dependencies.Cli;
using Fingerprinting.StepHost;

// Stdout guarded and invariant culture, as every step; no MSBuildLocator —
// step 6 never loads MSBuild, and ships NuGet's own client libraries.
var stdout = StepBootstrap.Initialise(registerMsBuild: false);

return await DependencyAssessmentCli.RunAsync(args, Console.In, stdout, Console.Error);
