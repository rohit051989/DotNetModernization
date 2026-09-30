using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>How to infer a binding source for a parameter with no
/// <c>[From*]</c> attribute.</summary>
public enum BindingInference
{
    /// <summary>MVC / MVC 5: binding reads several sources; only a route
    /// parameter name is certain.</summary>
    None,

    /// <summary>ASP.NET Core <c>[ApiController]</c> conventions: route
    /// name → route, IFormFile → form, simple type → query, complex → body.</summary>
    ApiController,

    /// <summary>Minimal APIs: as above, except a complex type may be the
    /// body or a DI service — not decidable without binding, so left null.</summary>
    MinimalApi,
}

/// <summary><c>parameters[]</c> on the http block — Part B3.</summary>
public static class HttpParameters
{
    private static readonly IReadOnlyDictionary<string, string?> ExplicitSources = new Dictionary<string, string?>(StringComparer.Ordinal)
    {
        ["FromRoute"] = ParameterSources.Route,
        ["FromQuery"] = ParameterSources.Query,
        ["FromBody"] = ParameterSources.Body,
        ["FromHeader"] = ParameterSources.Header,
        ["FromForm"] = ParameterSources.Form,
        // Web API 2.
        ["FromUri"] = ParameterSources.Query,
        // Not HTTP input at all.
        ["FromServices"] = null,
        ["FromKeyedServices"] = null,
    };

    /// <summary>Framework-supplied, never bound from the request.</summary>
    private static readonly IReadOnlySet<string> NotRequestInput = new HashSet<string>(StringComparer.Ordinal)
    {
        "CancellationToken", "HttpContext", "HttpRequest", "HttpResponse", "ClaimsPrincipal", "ServerCallContext",
    };

    private static readonly IReadOnlySet<string> FormTypes = new HashSet<string>(StringComparer.Ordinal)
    {
        "IFormFile", "IFormFileCollection",
    };

    private static readonly IReadOnlySet<string> SimpleTypes = new HashSet<string>(StringComparer.Ordinal)
    {
        "string", "String", "int", "Int32", "long", "Int64", "short", "Int16", "byte", "Byte", "sbyte", "SByte",
        "uint", "UInt32", "ulong", "UInt64", "ushort", "UInt16", "bool", "Boolean", "decimal", "Decimal",
        "double", "Double", "float", "Single", "char", "Char", "Guid", "DateTime", "DateTimeOffset", "TimeSpan",
        "DateOnly", "TimeOnly", "Uri",
    };

    public static IReadOnlyList<HttpParameter> Build(
        BaseParameterListSyntax? parameters, string? routeTemplate, BindingInference inference)
    {
        if (parameters is null)
        {
            return [];
        }

        var routeNames = RouteTemplates.ParameterNames(routeTemplate);
        var result = new List<HttpParameter>();

        foreach (var parameter in parameters.Parameters)
        {
            var typeText = parameter.Type is null ? null : SyntaxHelpers.Collapse(parameter.Type.ToString());
            var typeName = parameter.Type is null ? null : BaseTypeName(parameter.Type);
            if (typeName is not null && NotRequestInput.Contains(typeName))
            {
                continue;
            }

            string? explicitSource = null;
            var isService = false;
            foreach (var (_, name) in SyntaxHelpers.Attributes(parameter.AttributeLists))
            {
                if (ExplicitSources.TryGetValue(name, out var source))
                {
                    if (source is null)
                    {
                        isService = true;
                    }

                    explicitSource ??= source;
                }
            }

            if (isService)
            {
                continue;
            }

            var parameterName = parameter.Identifier.Text;
            if (explicitSource is not null)
            {
                result.Add(new HttpParameter { Name = parameterName, Type = typeText, Source = explicitSource });
                continue;
            }

            result.Add(new HttpParameter
            {
                Name = parameterName,
                Type = typeText,
                Source = ParameterSources.Inferred,
                InferredSource = Infer(parameterName, parameter.Type, typeName, routeNames, inference),
            });
        }

        return result;
    }

    private static string? Infer(
        string name, TypeSyntax? type, string? typeName, IReadOnlySet<string> routeNames, BindingInference inference)
    {
        if (routeNames.Contains(name))
        {
            return ParameterSources.Route;
        }

        if (typeName is not null && FormTypes.Contains(typeName))
        {
            return ParameterSources.Form;
        }

        if (inference == BindingInference.None || type is null)
        {
            return null;
        }

        if (IsSimple(type))
        {
            return ParameterSources.Query;
        }

        return inference == BindingInference.ApiController ? ParameterSources.Body : null;
    }

    private static bool IsSimple(TypeSyntax type) => type switch
    {
        NullableTypeSyntax nullable => IsSimple(nullable.ElementType),
        PredefinedTypeSyntax predefined => SimpleTypes.Contains(predefined.Keyword.Text),
        GenericNameSyntax { Identifier.Text: "Nullable", TypeArgumentList.Arguments: [var inner] } => IsSimple(inner),
        _ => BaseTypeName(type) is { } name && SimpleTypes.Contains(name),
    };

    private static string? BaseTypeName(TypeSyntax type) => type switch
    {
        NullableTypeSyntax nullable => BaseTypeName(nullable.ElementType),
        PredefinedTypeSyntax predefined => predefined.Keyword.Text,
        ArrayTypeSyntax => null,
        _ => SyntaxHelpers.RightmostTypeName(type),
    };
}
