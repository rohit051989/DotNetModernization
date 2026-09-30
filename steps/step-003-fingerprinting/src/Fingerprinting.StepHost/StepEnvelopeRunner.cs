using System.Text.Json;

namespace Fingerprinting.StepHost;

/// <summary>
/// The process-adapter half of 11-STEP-CONTRACT.md: a StepContext on stdin,
/// a StepResult on stdout and nothing else. Shared so every step parses the
/// envelope, handles a failure and writes its result the same way.
/// </summary>
public static class StepEnvelopeRunner
{
    public static async Task<int> RunAsync(
        TextReader input, TextWriter output, TextWriter error, Func<StepContextEnvelope, Task<StepResult>> execute)
    {
        StepContextEnvelope context;
        try
        {
            // lstrip a BOM: PowerShell's `Get-Content | ...exe` (the documented
            // standalone invocation) can inject one — same guard as step 2.
            var raw = (await input.ReadToEndAsync()).TrimStart('﻿');
            context = JsonSerializer.Deserialize<StepContextEnvelope>(raw, EnvelopeJson.Options)
                ?? throw new InvalidOperationException("StepContext deserialized to null");
        }
        catch (Exception ex)
        {
            // Nothing to build a StepResult against — the process adapter's
            // fallback path (non-zero exit, stderr tail) applies here.
            error.WriteLine($"Fatal: could not parse StepContext from stdin: {ex}");
            return 1;
        }

        StepResult result;
        try
        {
            result = await execute(context);
        }
        catch (Exception ex)
        {
            result = new StepResult { ExitStatus = ExitStatuses.Failed, ExitMessage = $"{ex.GetType().Name}: {ex.Message}" };
        }

        output.Write(JsonSerializer.Serialize(result, EnvelopeJson.Options));
        return 0;
    }

    public static StepResult Failed(string message) => new() { ExitStatus = ExitStatuses.Failed, ExitMessage = message };

    public static Guid? TryParseGuid(string? value) => Guid.TryParse(value, out var guid) ? guid : null;
}
