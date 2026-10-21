using System.Text.Json.Nodes;

namespace Fingerprinting.StepHost;

/// <summary>
/// release 5: every field an artifact schema lists as required that holds text holds some — an empty string in a
/// required field is a record the step did not finish, even where the schema's type allows it. Read from the schema
/// itself (<c>required</c>, <c>properties</c>, <c>items</c>, <c>$ref</c>, and the branches of <c>allOf</c>, <c>anyOf</c>,
/// <c>oneOf</c>), so a new required field is covered without a change here.
/// </summary>
public static class RequiredFields
{
    /// <summary>The JSON pointer of every required field that is an empty string.</summary>
    public static IReadOnlyList<string> Empty(string artifactJson, string schemaJson)
    {
        var schema = JsonNode.Parse(schemaJson)!.AsObject();
        var found = new List<string>();
        Walk(JsonNode.Parse(artifactJson), schema, schema, "", found, 0);
        return found;
    }

    private static void Walk(JsonNode? value, JsonObject node, JsonObject root, string pointer, List<string> found, int depth)
    {
        if (value is null || depth > 64)
        {
            return;
        }

        foreach (var branch in Branches(node, root))
        {
            if (value is JsonObject obj)
            {
                var required = branch["required"] is JsonArray names ? names.Select(n => n!.GetValue<string>()).ToHashSet() : [];
                foreach (var name in required)
                {
                    if (obj[name] is JsonValue v && v.TryGetValue<string>(out var text) && text.Length == 0)
                    {
                        found.Add($"{pointer}/{name}");
                    }
                }

                if (branch["properties"] is JsonObject properties)
                {
                    foreach (var (name, sub) in properties)
                    {
                        if (sub is JsonObject subSchema && obj[name] is { } child)
                        {
                            Walk(child, subSchema, root, $"{pointer}/{name}", found, depth + 1);
                        }
                    }
                }
            }
            else if (value is JsonArray array && branch["items"] is JsonObject items)
            {
                for (var i = 0; i < array.Count; i++)
                {
                    Walk(array[i], items, root, $"{pointer}/{i}", found, depth + 1);
                }
            }
        }
    }

    /// <summary>A schema node and every node it stands for: its <c>$ref</c> target, and its combinator branches.</summary>
    private static IEnumerable<JsonObject> Branches(JsonObject node, JsonObject root)
    {
        var seen = new HashSet<JsonObject>(ReferenceEqualityComparer.Instance);
        var pending = new Stack<JsonObject>([node]);
        while (pending.Count > 0)
        {
            var current = pending.Pop();
            if (!seen.Add(current))
            {
                continue;
            }

            yield return current;
            if (current["$ref"] is JsonValue reference && Resolve(root, reference.GetValue<string>()) is { } target)
            {
                pending.Push(target);
            }

            foreach (var combinator in new[] { "allOf", "anyOf", "oneOf" })
            {
                if (current[combinator] is JsonArray branches)
                {
                    foreach (var branch in branches.OfType<JsonObject>())
                    {
                        pending.Push(branch);
                    }
                }
            }
        }
    }

    private static JsonObject? Resolve(JsonObject root, string reference)
    {
        if (!reference.StartsWith("#/", StringComparison.Ordinal))
        {
            return null;
        }

        JsonNode? current = root;
        foreach (var segment in reference[2..].Split('/'))
        {
            current = current?[segment.Replace("~1", "/").Replace("~0", "~")];
        }

        return current as JsonObject;
    }
}
