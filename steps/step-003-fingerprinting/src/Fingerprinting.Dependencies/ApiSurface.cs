using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

namespace Fingerprinting.Dependencies;

/// <summary>One public or protected member, as its signature reads. For a
/// method, its parameter types, how many arguments a call may pass
/// (<see cref="MinArgs"/> to <see cref="MaxArgs"/>; optional and params
/// parameters widen the range) and whether it overrides a base member — a
/// removed override leaves calls bound to the base, so it is not a break.</summary>
public sealed record ApiMember(string Name, string Signature, bool IsExtension)
{
    public IReadOnlyList<string>? Parameters { get; init; }
    public string? ReturnType { get; init; }
    public int GenericArity { get; init; }
    public int MinArgs { get; init; }
    public int MaxArgs { get; init; }
    public bool IsOverride { get; init; }
}

/// <summary>One public type: its full name (namespace included, nested types
/// joined with '+'), its simple name as code writes it, and its members.</summary>
public sealed record ApiType(string FullName, string Namespace, string SimpleName, IReadOnlyList<ApiMember> Members);

/// <summary>A change to the public surface between two versions.</summary>
/// <param name="Change">type_removed, member_removed or signature_changed.</param>
/// <param name="MinArgs">For a method, the argument counts a call to the old
/// signature could have used; null for properties, fields and events.</param>
/// <param name="UnchangedOverloads">Argument ranges of same-name methods on
/// the type that did not change. A call whose argument count one of them
/// accepts may bind to it instead: syntax alone cannot tell, so the call
/// site is ambiguous rather than confirmed.</param>
public sealed record ApiChange(string Change, ApiType Type, string? Member, string? OldSignature, IReadOnlyList<string> NewSignatures, bool IsExtension,
    int? MinArgs = null, int? MaxArgs = null, IReadOnlyList<(int Min, int Max)>? UnchangedOverloads = null);

/// <summary>
/// The public surface of a set of assemblies, read with
/// System.Reflection.Metadata — nothing is loaded or executed — and the
/// difference between two of them (Part C4). Removed types, removed members
/// and changed signatures; additions never break a caller and are ignored.
/// A type forwarded to another assembly is not removed.
/// </summary>
public static class ApiSurface
{
    public static IReadOnlyDictionary<string, ApiType> Read(IEnumerable<string> assemblyPaths)
    {
        var types = new Dictionary<string, ApiType>(StringComparer.Ordinal);
        foreach (var path in assemblyPaths)
        {
            using var stream = File.OpenRead(path);
            using var pe = new PEReader(stream);
            if (!pe.HasMetadata) continue;
            var reader = pe.GetMetadataReader();
            var provider = new SignatureNames(reader);

            foreach (var handle in reader.TypeDefinitions)
            {
                var type = reader.GetTypeDefinition(handle);
                if (!IsVisible(reader, type)) continue;
                var (fullName, ns, simple) = Names(reader, type);
                var members = new List<ApiMember>();

                foreach (var methodHandle in type.GetMethods())
                {
                    var method = reader.GetMethodDefinition(methodHandle);
                    if (!IsVisibleMember(method.Attributes & MethodAttributes.MemberAccessMask)) continue;
                    var name = reader.GetString(method.Name);
                    // Accessors are covered by their property or event.
                    if ((method.Attributes & MethodAttributes.SpecialName) != 0 && name != ".ctor" && !name.StartsWith("op_", StringComparison.Ordinal)) continue;
                    var signature = method.DecodeSignature(provider, null);
                    var parameters = string.Join(",", signature.ParameterTypes);
                    var generic = signature.GenericParameterCount > 0 ? $"``{signature.GenericParameterCount}" : "";
                    var isExtension = method.GetCustomAttributes().Any(a => AttributeName(reader, reader.GetCustomAttribute(a)) == "System.Runtime.CompilerServices.ExtensionAttribute");
                    var (minArgs, maxArgs) = ArgumentRange(reader, method, signature.ParameterTypes.Length);
                    var isOverride = (method.Attributes & MethodAttributes.Virtual) != 0 && (method.Attributes & MethodAttributes.NewSlot) == 0;
                    members.Add(new ApiMember(name, $"{name}{generic}({parameters}):{signature.ReturnType}", isExtension)
                    {
                        Parameters = signature.ParameterTypes,
                        ReturnType = signature.ReturnType,
                        GenericArity = signature.GenericParameterCount,
                        MinArgs = minArgs,
                        MaxArgs = maxArgs,
                        IsOverride = isOverride,
                    });
                }

                foreach (var propertyHandle in type.GetProperties())
                {
                    var property = reader.GetPropertyDefinition(propertyHandle);
                    var accessors = property.GetAccessors();
                    var getter = accessors.Getter.IsNil ? (MethodAttributes?)null : reader.GetMethodDefinition(accessors.Getter).Attributes & MethodAttributes.MemberAccessMask;
                    var setter = accessors.Setter.IsNil ? (MethodAttributes?)null : reader.GetMethodDefinition(accessors.Setter).Attributes & MethodAttributes.MemberAccessMask;
                    if (!(getter is { } g && IsVisibleMember(g)) && !(setter is { } s && IsVisibleMember(s))) continue;
                    var name = reader.GetString(property.Name);
                    var signature = property.DecodeSignature(provider, null);
                    var index = signature.ParameterTypes.Length > 0 ? $"[{string.Join(",", signature.ParameterTypes)}]" : "";
                    var access = $"{(getter is { } gv && IsVisibleMember(gv) ? "get;" : "")}{(setter is { } sv && IsVisibleMember(sv) ? "set;" : "")}";
                    members.Add(new ApiMember(name, $"{name}{index}:{signature.ReturnType}{{{access}}}", false));
                }

                foreach (var fieldHandle in type.GetFields())
                {
                    var field = reader.GetFieldDefinition(fieldHandle);
                    var access = (MethodAttributes)(int)(field.Attributes & FieldAttributes.FieldAccessMask);
                    if (!IsVisibleMember(access) || (field.Attributes & FieldAttributes.SpecialName) != 0) continue;
                    var name = reader.GetString(field.Name);
                    members.Add(new ApiMember(name, $"{name}:{field.DecodeSignature(provider, null)}", false));
                }

                foreach (var eventHandle in type.GetEvents())
                {
                    var @event = reader.GetEventDefinition(eventHandle);
                    var adder = @event.GetAccessors().Adder;
                    if (adder.IsNil || !IsVisibleMember(reader.GetMethodDefinition(adder).Attributes & MethodAttributes.MemberAccessMask)) continue;
                    var name = reader.GetString(@event.Name);
                    members.Add(new ApiMember(name, $"event {name}", false));
                }

                types[fullName] = new ApiType(fullName, ns, simple, members.OrderBy(m => m.Signature, StringComparer.Ordinal).ToList());
            }

            // Forwarded types still exist for a caller.
            foreach (var exportedHandle in reader.ExportedTypes)
            {
                var exported = reader.GetExportedType(exportedHandle);
                var ns = reader.GetString(exported.Namespace);
                var name = reader.GetString(exported.Name);
                var fullName = ns.Length == 0 ? name : $"{ns}.{name}";
                types.TryAdd(fullName, new ApiType(fullName, ns, StripArity(name), [new ApiMember("*", "*forwarded*", false)]));
            }
        }

        return types;
    }

    public static IReadOnlyList<ApiChange> Compare(IReadOnlyDictionary<string, ApiType> before, IReadOnlyDictionary<string, ApiType> after)
    {
        var changes = new List<ApiChange>();
        foreach (var (fullName, oldType) in before.OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            if (!after.TryGetValue(fullName, out var newType))
            {
                changes.Add(new ApiChange("type_removed", oldType, null, null, [], false));
                continue;
            }

            // A forwarded type's members live elsewhere; not compared.
            if (newType.Members.Any(m => m.Signature == "*forwarded*")) continue;

            var newByName = newType.Members.GroupBy(m => m.Name, StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
            foreach (var group in oldType.Members.GroupBy(m => m.Name, StringComparer.Ordinal))
            {
                // A removed override: calls and base.X() bind to the base
                // member instead, so only non-overrides can break a caller.
                var candidates = group.Where(m => !m.IsOverride).ToList();
                if (!newByName.TryGetValue(group.Key, out var newMembers))
                {
                    if (candidates.Count == 0) continue;
                    var (min, max) = Range(candidates);
                    changes.Add(new ApiChange("member_removed", oldType, group.Key, candidates[0].Signature, [], candidates.Any(m => m.IsExtension), min, max));
                    continue;
                }

                var newSignatures = newMembers.Select(m => m.Signature).ToHashSet(StringComparer.Ordinal);
                bool Unchanged(ApiMember m) => newSignatures.Contains(m.Signature) || newMembers.Any(n => StillCallable(m, n));
                var unchanged = group.Where(m => m.Parameters is not null && Unchanged(m)).Select(m => (m.MinArgs, m.MaxArgs)).Distinct().ToList();
                foreach (var member in candidates.Where(m => !Unchanged(m)))
                {
                    changes.Add(new ApiChange("signature_changed", oldType, group.Key, member.Signature, newSignatures.Order(StringComparer.Ordinal).ToList(), member.IsExtension,
                        member.Parameters is null ? null : member.MinArgs, member.Parameters is null ? null : member.MaxArgs, unchanged));
                }
            }
        }

        return changes;
    }

    /// <summary>
    /// An old method signature a caller can still compile against: a new
    /// overload with the same name, generic arity and return type whose
    /// parameters begin with the old ones and whose extra parameters are all
    /// optional — the "added an optional parameter" change, which is
    /// source-compatible (the caller is recompiled) though not binary-compatible.
    /// </summary>
    private static bool StillCallable(ApiMember old, ApiMember candidate) =>
        old.Parameters is { } oldParameters && candidate.Parameters is { } newParameters
        && old.GenericArity == candidate.GenericArity
        && old.ReturnType == candidate.ReturnType
        && newParameters.Count >= oldParameters.Count
        && newParameters.Take(oldParameters.Count).SequenceEqual(oldParameters, StringComparer.Ordinal)
        && candidate.MinArgs <= oldParameters.Count;

    private static (int? Min, int? Max) Range(IReadOnlyList<ApiMember> members) =>
        members.All(m => m.Parameters is not null) ? (members.Min(m => m.MinArgs), members.Max(m => m.MaxArgs)) : (null, null);

    /// <summary>How many arguments a call may pass: parameters without a
    /// default are required; a trailing params array allows any number.</summary>
    private static (int Min, int Max) ArgumentRange(MetadataReader reader, MethodDefinition method, int count)
    {
        var required = count;
        var max = count;
        foreach (var handle in method.GetParameters())
        {
            var parameter = reader.GetParameter(handle);
            if (parameter.SequenceNumber == 0) continue;
            if ((parameter.Attributes & (ParameterAttributes.Optional | ParameterAttributes.HasDefault)) != 0)
            {
                required = Math.Min(required, parameter.SequenceNumber - 1);
            }

            if (parameter.SequenceNumber == count
                && parameter.GetCustomAttributes().Any(a => AttributeName(reader, reader.GetCustomAttribute(a)) == "System.ParamArrayAttribute"))
            {
                required = Math.Min(required, count - 1);
                max = int.MaxValue;
            }
        }

        return (required, max);
    }

    private static bool IsVisibleMember(MethodAttributes access) =>
        access is MethodAttributes.Public or MethodAttributes.Family or MethodAttributes.FamORAssem;

    private static bool IsVisible(MetadataReader reader, TypeDefinition type)
    {
        var visibility = type.Attributes & TypeAttributes.VisibilityMask;
        if (visibility == TypeAttributes.Public) return true;
        if (visibility is TypeAttributes.NestedPublic or TypeAttributes.NestedFamily or TypeAttributes.NestedFamORAssem)
        {
            return IsVisible(reader, reader.GetTypeDefinition(type.GetDeclaringType()));
        }

        return false;
    }

    private static (string FullName, string Namespace, string SimpleName) Names(MetadataReader reader, TypeDefinition type)
    {
        var name = reader.GetString(type.Name);
        if (type.GetDeclaringType().IsNil)
        {
            var ns = reader.GetString(type.Namespace);
            return (ns.Length == 0 ? name : $"{ns}.{name}", ns, StripArity(name));
        }

        var (outer, outerNs, _) = Names(reader, reader.GetTypeDefinition(type.GetDeclaringType()));
        return ($"{outer}+{name}", outerNs, StripArity(name));
    }

    public static string StripArity(string name)
    {
        var tick = name.IndexOf('`');
        return tick < 0 ? name : name[..tick];
    }

    private static string? AttributeName(MetadataReader reader, CustomAttribute attribute)
    {
        if (attribute.Constructor.Kind == HandleKind.MemberReference)
        {
            var parent = reader.GetMemberReference((MemberReferenceHandle)attribute.Constructor).Parent;
            if (parent.Kind == HandleKind.TypeReference)
            {
                var type = reader.GetTypeReference((TypeReferenceHandle)parent);
                return $"{reader.GetString(type.Namespace)}.{reader.GetString(type.Name)}";
            }
        }
        else if (attribute.Constructor.Kind == HandleKind.MethodDefinition)
        {
            var type = reader.GetTypeDefinition(reader.GetMethodDefinition((MethodDefinitionHandle)attribute.Constructor).GetDeclaringType());
            return $"{reader.GetString(type.Namespace)}.{reader.GetString(type.Name)}";
        }

        return null;
    }

    /// <summary>Type names as signatures spell them; generic context by
    /// position (!0, !!0) so a renamed type parameter is not a change.</summary>
    private sealed class SignatureNames(MetadataReader reader) : ISignatureTypeProvider<string, object?>
    {
        public string GetArrayType(string elementType, ArrayShape shape) => $"{elementType}[{new string(',', shape.Rank - 1)}]";
        public string GetByReferenceType(string elementType) => $"{elementType}&";
        public string GetFunctionPointerType(MethodSignature<string> signature) => $"fnptr({string.Join(",", signature.ParameterTypes)}):{signature.ReturnType}";
        public string GetGenericInstantiation(string genericType, ImmutableArray<string> typeArguments) => $"{genericType}<{string.Join(",", typeArguments)}>";
        public string GetGenericMethodParameter(object? genericContext, int index) => $"!!{index}";
        public string GetGenericTypeParameter(object? genericContext, int index) => $"!{index}";
        public string GetModifiedType(string modifier, string unmodifiedType, bool isRequired) => unmodifiedType;
        public string GetPinnedType(string elementType) => elementType;
        public string GetPointerType(string elementType) => $"{elementType}*";
        public string GetPrimitiveType(PrimitiveTypeCode typeCode) => typeCode.ToString();
        public string GetSZArrayType(string elementType) => $"{elementType}[]";

        public string GetTypeFromDefinition(MetadataReader _, TypeDefinitionHandle handle, byte rawTypeKind)
        {
            var type = reader.GetTypeDefinition(handle);
            var name = reader.GetString(type.Name);
            if (!type.GetDeclaringType().IsNil) return $"{GetTypeFromDefinition(reader, type.GetDeclaringType(), 0)}+{name}";
            var ns = reader.GetString(type.Namespace);
            return ns.Length == 0 ? name : $"{ns}.{name}";
        }

        public string GetTypeFromReference(MetadataReader _, TypeReferenceHandle handle, byte rawTypeKind)
        {
            var type = reader.GetTypeReference(handle);
            var name = reader.GetString(type.Name);
            if (type.ResolutionScope.Kind == HandleKind.TypeReference)
            {
                return $"{GetTypeFromReference(reader, (TypeReferenceHandle)type.ResolutionScope, 0)}+{name}";
            }

            var ns = reader.GetString(type.Namespace);
            return ns.Length == 0 ? name : $"{ns}.{name}";
        }

        public string GetTypeFromSpecification(MetadataReader _, object? genericContext, TypeSpecificationHandle handle, byte rawTypeKind) =>
            reader.GetTypeSpecification(handle).DecodeSignature(this, genericContext);
    }
}
