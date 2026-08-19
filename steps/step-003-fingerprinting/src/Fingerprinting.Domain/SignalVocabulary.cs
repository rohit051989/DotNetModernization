namespace Fingerprinting.Domain;

/// <summary>
/// The sixteen fingerprint categories from step-3-application-fingerprinting.md
/// section 19, SCREAMING_SNAKE_CASE per 21-STEP-003-FINGERPRINTING.md Part D.
/// Mirrors the SIGNAL_CATEGORY tuple in backend/app/models.py — keep both in
/// sync; renaming either without the other breaks DB writes.
/// </summary>
public static class SignalCategories
{
    public const string ProjectMetadata = "PROJECT_METADATA";
    public const string FrameworkReference = "FRAMEWORK_REFERENCE";
    public const string PackageDependency = "PACKAGE_DEPENDENCY";
    public const string SourceConstruct = "SOURCE_CONSTRUCT";
    public const string FileIndicator = "FILE_INDICATOR";
    public const string ConfigurationIndicator = "CONFIGURATION_INDICATOR";
    public const string EntryPoint = "ENTRY_POINT";
    public const string EndpointIndicator = "ENDPOINT_INDICATOR";
    public const string ExecutionIndicator = "EXECUTION_INDICATOR";
    public const string HostingIndicator = "HOSTING_INDICATOR";
    public const string UiIndicator = "UI_INDICATOR";
    public const string DataAccessIndicator = "DATA_ACCESS_INDICATOR";
    public const string MessagingIndicator = "MESSAGING_INDICATOR";
    public const string SchedulingIndicator = "SCHEDULING_INDICATOR";
    public const string DeploymentIndicator = "DEPLOYMENT_INDICATOR";
    public const string TestingIndicator = "TESTING_INDICATOR";
}

/// <summary>
/// The ten <c>fingerprint_signals.signal_type</c> values from
/// 21-STEP-003-FINGERPRINTING.md Part E.
/// </summary>
public static class SignalTypes
{
    public const string Attribute = "ATTRIBUTE";
    public const string BaseClass = "BASE_CLASS";
    public const string FilePresence = "FILE_PRESENCE";
    public const string Invocation = "INVOCATION";
    public const string ConfigElement = "CONFIG_ELEMENT";
    public const string Package = "PACKAGE";
    public const string Assembly = "ASSEMBLY";
    public const string Namespace = "NAMESPACE";
    public const string Route = "ROUTE";
    public const string EntryPoint = "ENTRY_POINT";
}

/// <summary>
/// The nine evidence source types from step-3-application-fingerprinting.md
/// section 18.
/// </summary>
public static class EvidenceSourceTypes
{
    public const string ProjectFile = "PROJECT_FILE";
    public const string SourceCode = "SOURCE_CODE";
    public const string Configuration = "CONFIGURATION";
    public const string FileStructure = "FILE_STRUCTURE";
    public const string PackageReference = "PACKAGE_REFERENCE";
    public const string AssemblyReference = "ASSEMBLY_REFERENCE";
    public const string Pipeline = "PIPELINE";
    public const string DeploymentScript = "DEPLOYMENT_SCRIPT";
    public const string SolutionMetadata = "SOLUTION_METADATA";
}
