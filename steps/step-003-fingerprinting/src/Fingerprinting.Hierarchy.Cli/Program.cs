using Fingerprinting.Hierarchy.Cli;
using Fingerprinting.StepHost;

// Stdout guarded and invariant culture, as every step; no MSBuildLocator — dependency-hierarchy never loads MSBuild.
var stdout = StepBootstrap.Initialise(registerMsBuild: false);

return await DependencyHierarchyCli.RunAsync(args, Console.In, stdout, Console.Error);
