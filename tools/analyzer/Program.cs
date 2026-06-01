using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

/// <summary>
/// SQL to DynamoDB Design Mentor Roslyn Analyzer — Extracts entities, relationships, and data access methods
/// from a .NET/C# codebase using Roslyn's semantic analysis (AST + type resolution).
/// Outputs structured JSON for the SQL to DynamoDB Design Mentor pipeline to consume.
/// </summary>

// --- Output models ---
record FieldInfo(string Name, string Type, int? MaxLength, bool IsKey, bool IsNavigation, bool IsRequired = false, string? ColumnName = null);
record RelationshipInfo(string Target, string Type, string? NavigationProperty, string? ForeignKey);
record ParameterInfo(string Name, string Type);
record IndexInfo(string EntityName, List<string> Properties, bool IsUnique);

// Structured access pattern details extracted from LINQ chains
record AccessPatternDetails(
    List<string> FilterFields,          // Fields used in .Where() predicates (e.g., ["Email", "IsActive"])
    List<string> SortFields,            // Fields used in .OrderBy/.OrderByDescending (e.g., ["CreatedDate DESC"])
    List<string> IncludeChains,         // .Include/.ThenInclude chains (e.g., ["Items.Product"])
    List<string> ProjectionFields,      // Fields in .Select() projections (e.g., ["Id", "Name", "Email"])
    List<string> GroupByFields,         // Fields in .GroupBy() (e.g., ["CategoryId"])
    string? Aggregation,                // Aggregation type if any (Count, Sum, Average, Min, Max)
    bool HasPagination,                 // Uses .Skip()/.Take()
    bool IsTransaction,                 // Method has multiple entity changes + SaveChanges
    int EntityChangeCount               // Number of Add/Update/Remove calls before SaveChanges
);

record AccessMethodInfo(
    string File, string Class, string Method, string ReturnType,
    List<ParameterInfo> Parameters, string? LinqExpression, List<string> Entities,
    string Operation, List<string> Callers, int LineNumber,
    bool IsDbQuery = true, AccessPatternDetails? PatternDetails = null);
record EntityInfo(string Name, string? Table, List<FieldInfo> Fields, List<RelationshipInfo> Relationships, string Source = "directory");
record StoredProcRef(string Name, string CalledFrom, string File, int LineNumber);

record AnalysisReport(
    string ProjectPath,
    int TotalCsFiles,
    int FilesAnalyzed,
    bool EfCoreDetected,
    bool DapperDetected,
    bool RawSqlDetected,
    List<EntityInfo> Entities,
    List<AccessMethodInfo> AccessMethods,
    List<AccessMethodInfo> SupplementaryMethods,
    List<StoredProcRef> StoredProcedures,
    List<IndexInfo> Indexes,
    List<string> Warnings);

class RoslynAnalyzer
{
    private readonly string _projectPath;
    private readonly List<string> _warnings = new();
    private readonly HashSet<string> _ownedTypes = new();    // Types marked as [Owned] or OwnsOne/OwnsMany
    private readonly HashSet<string> _notMappedTypes = new(); // Types marked as [NotMapped]
    private readonly HashSet<string> _ownedNavigationProps = new(); // Navigation property names from OwnsOne lambda form
    private readonly List<IndexInfo> _indexes = new();

    // --- Improved singularization with irregular plural handling ---
    private static readonly Dictionary<string, string> IrregularPlurals = new(StringComparer.OrdinalIgnoreCase)
    {
        { "People", "Person" }, { "Children", "Child" }, { "Men", "Man" }, { "Women", "Woman" },
        { "Mice", "Mouse" }, { "Geese", "Goose" }, { "Teeth", "Tooth" }, { "Feet", "Foot" },
        { "Data", "Datum" }, { "Criteria", "Criterion" }, { "Analyses", "Analysis" },
        { "Statuses", "Status" }, { "Addresses", "Address" }, { "Processes", "Process" },
        { "Classes", "Class" }, { "Buses", "Bus" }, { "Matrices", "Matrix" },
        { "Indices", "Index" }, { "Vertices", "Vertex" }, { "Appendices", "Appendix" },
    };

    private static string Singularize(string plural)
    {
        if (IrregularPlurals.TryGetValue(plural, out var irregular))
            return irregular;
        if (plural.EndsWith("ies") && plural.Length > 4)
            return plural[..^3] + "y";
        if (plural.EndsWith("ses") || plural.EndsWith("xes") || plural.EndsWith("zes") ||
            plural.EndsWith("ches") || plural.EndsWith("shes"))
            return plural[..^2];
        if (plural.EndsWith("s") && !plural.EndsWith("ss") && plural.Length > 2)
            return plural[..^1];
        return plural;
    }

    public RoslynAnalyzer(string projectPath)
    {
        _projectPath = projectPath;
    }

    public AnalysisReport Analyze()
    {
        var csFiles = Directory.GetFiles(_projectPath, "*.cs", SearchOption.AllDirectories)
            .Where(f => !f.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}.git{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}Migrations{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}Tests{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}Test{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}UnitTests{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}IntegrationTests{Path.DirectorySeparatorChar}")
                     && !f.Contains($"{Path.DirectorySeparatorChar}FunctionalTests{Path.DirectorySeparatorChar}")
                     && !f.EndsWith("Tests.cs") && !f.EndsWith("Test.cs"))
            .ToList();

        var trees = csFiles.Select(f =>
        {
            var code = File.ReadAllText(f);
            return CSharpSyntaxTree.ParseText(code, path: f);
        }).ToList();

        var refs = new List<MetadataReference>
        {
            MetadataReference.CreateFromFile(typeof(object).Assembly.Location),
            MetadataReference.CreateFromFile(typeof(Enumerable).Assembly.Location),
            MetadataReference.CreateFromFile(typeof(Console).Assembly.Location),
        };
        var runtimeDir = Path.GetDirectoryName(typeof(object).Assembly.Location)!;
        foreach (var dll in Directory.GetFiles(runtimeDir, "System.*.dll"))
        {
            try { refs.Add(MetadataReference.CreateFromFile(dll)); } catch { }
        }

        var compilation = CSharpCompilation.Create("Analysis", trees, refs,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

        var entities = new List<EntityInfo>();
        var accessMethods = new List<AccessMethodInfo>();
        var storedProcs = new List<StoredProcRef>();
        var dbSetPropertyNames = new HashSet<string>();
        var dbSetToEntity = new Dictionary<string, string>(); // Maps "Orders" → "Order"
        bool efCore = false, dapper = false, rawSql = false;
        int filesAnalyzed = 0;

        // --- Pass 1: Detect [Owned], [NotMapped], and OwnsOne in IEntityTypeConfiguration ---
        foreach (var tree in trees)
        {
            var root = tree.GetRoot();
            foreach (var classDecl in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
            {
                var className = classDecl.Identifier.Text;

                // [Owned] and [NotMapped] attributes
                foreach (var attrList in classDecl.AttributeLists)
                {
                    foreach (var attr in attrList.Attributes)
                    {
                        var attrName = attr.Name.ToString();
                        if (attrName is "Owned") _ownedTypes.Add(className);
                        if (attrName is "NotMapped") _notMappedTypes.Add(className);
                    }
                }

                // Scan IEntityTypeConfiguration<T>.Configure() for OwnsOne/OwnsMany
                if (classDecl.BaseList != null)
                {
                    foreach (var baseType in classDecl.BaseList.Types)
                    {
                        var baseTypeName = baseType.ToString();
                        if (baseTypeName.StartsWith("IEntityTypeConfiguration<") && baseTypeName.EndsWith(">"))
                        {
                            // Find the Configure() method and scan for OwnsOne/OwnsMany
                            foreach (var method in classDecl.Members.OfType<MethodDeclarationSyntax>())
                            {
                                if (method.Identifier.Text == "Configure")
                                {
                                    ExtractFluentApiOwnedTypes(method);
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Pass 2: Main analysis ---
        foreach (var tree in trees)
        {
            var root = tree.GetRoot();
            var filePath = tree.FilePath;
            var relPath = Path.GetRelativePath(_projectPath, filePath);
            var model = compilation.GetSemanticModel(tree);
            filesAnalyzed++;

            foreach (var classDecl in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
            {
                var className = classDecl.Identifier.Text;

                // --- DbContext detection ---
                bool isDbContext = false;
                if (classDecl.BaseList != null)
                {
                    foreach (var baseType in classDecl.BaseList.Types)
                    {
                        var baseTypeName = baseType.ToString();
                        if (baseTypeName.Contains("DbContext") ||
                            baseTypeName.Contains("IdentityDbContext") ||
                            baseTypeName.Contains("ApiAuthorizationDbContext"))
                        {
                            isDbContext = true;
                            break;
                        }
                    }
                }
                if (!isDbContext)
                {
                    foreach (var prop in classDecl.Members.OfType<PropertyDeclarationSyntax>())
                    {
                        if (prop.Type.ToString().StartsWith("DbSet<"))
                        {
                            isDbContext = true;
                            break;
                        }
                    }
                }

                if (isDbContext)
                {
                    efCore = true;
                    ExtractDbContextEntities(classDecl, entities, relPath, dbSetPropertyNames, dbSetToEntity);
                }

                // --- OnModelCreating: relationships, owned types, indexes, many-to-many ---
                foreach (var method in classDecl.Members.OfType<MethodDeclarationSyntax>())
                {
                    if (method.Identifier.Text == "OnModelCreating")
                    {
                        ExtractFluentApiRelationships(method, entities);
                        ExtractFluentApiOwnedTypes(method);
                        ExtractFluentApiEntities(method, entities, ref efCore);
                        ExtractFluentApiIndexes(method);
                        ExtractFluentApiManyToMany(method, entities);
                        ExtractFluentApiForeignKeys(method, entities);
                    }
                }

                // --- Data access methods ---
                ExtractDataAccessMethods(classDecl, model, relPath, accessMethods, storedProcs,
                    ref dapper, ref rawSql, dbSetPropertyNames, dbSetToEntity);

                // --- [Table], [Keyless] attributes ---
                if (!_notMappedTypes.Contains(className) && !_ownedTypes.Contains(className))
                {
                    foreach (var attrList in classDecl.AttributeLists)
                    {
                        foreach (var attr in attrList.Attributes)
                        {
                            var attrName = attr.Name.ToString();
                            if (attrName is "Table" or "Keyless")
                            {
                                efCore = true;
                                if (!entities.Any(e => e.Name == className))
                                {
                                    var tableName = attrName == "Table" && attr.ArgumentList?.Arguments.Count > 0
                                        ? attr.ArgumentList.Arguments[0].ToString().Trim('"')
                                        : null;
                                    entities.Add(new EntityInfo(className, tableName, new(), new(), "attribute"));
                                }
                            }
                        }
                    }

                    // --- [Index] attribute on class ---
                    foreach (var attrList in classDecl.AttributeLists)
                    {
                        foreach (var attr in attrList.Attributes)
                        {
                            var attrName = attr.Name.ToString();
                            if (attrName is "Index")
                            {
                                var props = attr.ArgumentList?.Arguments
                                    .Select(a => a.ToString().Trim('"').Replace("nameof(", "").TrimEnd(')'))
                                    .ToList() ?? new();
                                bool isUnique = attr.ArgumentList?.Arguments
                                    .Any(a => a.ToString().Contains("IsUnique = true")) ?? false;
                                if (props.Count > 0)
                                    _indexes.Add(new IndexInfo(className, props, isUnique));
                            }
                        }
                    }
                }

                // --- IEntityTypeConfiguration<T> ---
                if (classDecl.BaseList != null)
                {
                    foreach (var baseType in classDecl.BaseList.Types)
                    {
                        var baseTypeName = baseType.ToString();
                        if (baseTypeName.StartsWith("IEntityTypeConfiguration<") && baseTypeName.EndsWith(">"))
                        {
                            efCore = true;
                            var entityName = baseTypeName[25..^1];
                            if (!entities.Any(e => e.Name == entityName) &&
                                !_ownedTypes.Contains(entityName) && !_notMappedTypes.Contains(entityName))
                            {
                                entities.Add(new EntityInfo(entityName, null, new(), new(), "entityconfig"));
                            }

                            // Scan Configure() for relationships, indexes, foreign keys, entities
                            foreach (var method in classDecl.Members.OfType<MethodDeclarationSyntax>())
                            {
                                if (method.Identifier.Text == "Configure")
                                {
                                    ExtractFluentApiRelationships(method, entities);
                                    ExtractFluentApiEntities(method, entities, ref efCore);
                                    ExtractFluentApiIndexes(method);
                                    ExtractFluentApiManyToMany(method, entities);
                                    ExtractFluentApiForeignKeys(method, entities);
                                }
                            }
                        }
                    }
                }
            }

            // --- Enrich confirmed entities with fields from class definitions ---
            foreach (var classDecl in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
            {
                var className = classDecl.Identifier.Text;
                var existing = entities.FirstOrDefault(e => e.Name == className && e.Fields.Count == 0);
                if (existing != null)
                {
                    var fields = ExtractFields(classDecl);
                    var rels = ExtractNavigationRelationships(classDecl);
                    if (fields.Count > 0 || rels.Count > 0)
                    {
                        entities.Remove(existing);
                        entities.Add(new EntityInfo(className, existing.Table, fields, rels, existing.Source));
                    }
                }
            }
        }

        // --- Post-processing: Resolve owned navigation properties to types ---
        // For lambda-form OwnsOne(o => o.ShipToAddress), we collected the property name.
        // Now match it against entity relationships to find the actual type.
        if (_ownedNavigationProps.Count > 0)
        {
            foreach (var entity in entities)
            {
                foreach (var rel in entity.Relationships)
                {
                    if (rel.NavigationProperty != null && _ownedNavigationProps.Contains(rel.NavigationProperty))
                    {
                        _ownedTypes.Add(rel.Target);
                    }
                }
                // Also check fields — the property name might match a field whose type is the owned class
                foreach (var field in entity.Fields)
                {
                    if (_ownedNavigationProps.Contains(field.Name) && char.IsUpper(field.Type[0])
                        && !field.Type.StartsWith("string") && !field.Type.StartsWith("int"))
                    {
                        _ownedTypes.Add(field.Type);
                    }
                }
            }
        }

        // --- Post-processing: Navigation property targets ---
        var knownEntityNames = new HashSet<string>(entities.Select(e => e.Name));
        var navTargets = new HashSet<string>();
        foreach (var entity in entities)
        {
            foreach (var rel in entity.Relationships)
            {
                if (!string.IsNullOrEmpty(rel.Target) && !knownEntityNames.Contains(rel.Target))
                    navTargets.Add(rel.Target);
            }
        }
        foreach (var tree in trees)
        {
            var root = tree.GetRoot();
            foreach (var classDecl in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
            {
                var className = classDecl.Identifier.Text;
                if (navTargets.Contains(className) && !knownEntityNames.Contains(className)
                    && !_ownedTypes.Contains(className) && !_notMappedTypes.Contains(className))
                {
                    var fields = ExtractFields(classDecl);
                    var rels = ExtractNavigationRelationships(classDecl);
                    entities.Add(new EntityInfo(className, null, fields, rels, "navigation"));
                    knownEntityNames.Add(className);
                }
            }
        }

        // --- Remove exclusions ---
        // Remove DbContext classes, [Owned] types, [NotMapped] types
        entities.RemoveAll(e => e.Name.EndsWith("Context") || e.Name.EndsWith("DbContext"));
        entities.RemoveAll(e => _ownedTypes.Contains(e.Name));
        entities.RemoveAll(e => _notMappedTypes.Contains(e.Name));

        // Split access methods: DB queries vs in-memory
        var dbMethods = accessMethods.Where(m => m.IsDbQuery).ToList();
        var supplementaryMethods = accessMethods.Where(m => !m.IsDbQuery).ToList();

        return new AnalysisReport(
            _projectPath, csFiles.Count, filesAnalyzed,
            efCore, dapper, rawSql,
            entities, dbMethods, supplementaryMethods, storedProcs, _indexes, _warnings);
    }

    // ========================================================================
    // Entity extraction
    // ========================================================================

    private void ExtractDbContextEntities(ClassDeclarationSyntax dbContext,
        List<EntityInfo> entities, string file, HashSet<string> dbSetPropertyNames,
        Dictionary<string, string> dbSetToEntity)
    {
        foreach (var prop in dbContext.Members.OfType<PropertyDeclarationSyntax>())
        {
            var typeStr = prop.Type.ToString();
            if (typeStr.StartsWith("DbSet<") && typeStr.EndsWith(">"))
            {
                var entityName = typeStr[6..^1];
                var propName = prop.Identifier.Text;
                dbSetPropertyNames.Add(propName);
                dbSetToEntity[propName] = entityName;
                if (!entities.Any(e => e.Name == entityName) &&
                    !_ownedTypes.Contains(entityName) && !_notMappedTypes.Contains(entityName))
                {
                    entities.Add(new EntityInfo(entityName, propName, new(), new(), "dbcontext"));
                }
            }
        }
    }

    private void ExtractFluentApiEntities(MethodDeclarationSyntax method,
        List<EntityInfo> entities, ref bool efCore)
    {
        foreach (var inv in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            foreach (var generic in inv.DescendantNodes().OfType<GenericNameSyntax>())
            {
                if (generic.Identifier.Text != "Entity") continue;
                if (generic.TypeArgumentList.Arguments.Count == 0) continue;
                var entityName = generic.TypeArgumentList.Arguments[0].ToString();
                if (_ownedTypes.Contains(entityName) || _notMappedTypes.Contains(entityName)) continue;
                if (entities.Any(e => e.Name == entityName)) continue;

                var chainText = inv.Parent?.ToString() ?? inv.ToString();
                string? tableName = null;
                if (chainText.Contains("ToTable("))
                {
                    var match = Regex.Match(chainText, @"ToTable\(""(\w+)""\)");
                    if (match.Success) tableName = match.Groups[1].Value;
                }
                entities.Add(new EntityInfo(entityName, tableName, new(), new(), "fluentapi"));
                efCore = true;
            }
        }
    }

    private void ExtractFluentApiOwnedTypes(MethodDeclarationSyntax method)
    {
        var bodyText = method.Body?.ToString() ?? "";
        foreach (var inv in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var invText = inv.Expression.ToString();
            if (!invText.Contains("OwnsOne") && !invText.Contains("OwnsMany")) continue;

            // Generic form: .OwnsOne<Address>() — extract type from generic argument
            foreach (var generic in inv.DescendantNodes().OfType<GenericNameSyntax>())
            {
                if (generic.Identifier.Text is "OwnsOne" or "OwnsMany")
                {
                    foreach (var typeArg in generic.TypeArgumentList.Arguments)
                    {
                        _ownedTypes.Add(typeArg.ToString());
                    }
                }
            }

            // Lambda form: .OwnsOne(o => o.ShipToAddress, ...) — extract the navigation property name
            // then resolve its type from the entity class later. For now, collect the property names
            // and match them against entity navigation properties to find the owned type.
            foreach (var lambda in inv.DescendantNodes().OfType<SimpleLambdaExpressionSyntax>())
            {
                if (lambda.Body is MemberAccessExpressionSyntax memberAccess)
                {
                    var navPropName = memberAccess.Name.Identifier.Text;
                    // The navigation property name often matches or contains the type name
                    // e.g., ShipToAddress → Address, ItemOrdered → CatalogItemOrdered
                    // Store the property name — we'll resolve it against known classes later
                    _ownedNavigationProps.Add(navPropName);
                }
            }
        }
    }

    private void ExtractFluentApiIndexes(MethodDeclarationSyntax method)
    {
        foreach (var inv in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var invText = inv.Expression.ToString();
            if (!invText.Contains("HasIndex")) continue;

            // Find the entity from Entity<T>() ancestor
            string? entityName = null;
            foreach (var ancestor in inv.Ancestors().OfType<InvocationExpressionSyntax>())
            {
                foreach (var generic in ancestor.DescendantNodes().OfType<GenericNameSyntax>())
                {
                    if (generic.Identifier.Text == "Entity" && generic.TypeArgumentList.Arguments.Count > 0)
                    {
                        entityName = generic.TypeArgumentList.Arguments[0].ToString();
                        break;
                    }
                }
                if (entityName != null) break;
            }

            if (entityName == null) continue;

            // Extract property names from the lambda: HasIndex(e => e.Email) or HasIndex(e => new { e.A, e.B })
            var props = new List<string>();
            foreach (var memberAccess in inv.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
            {
                var propName = memberAccess.Name.Identifier.Text;
                if (propName.Length > 0 && char.IsUpper(propName[0]))
                    props.Add(propName);
            }

            bool isUnique = inv.Parent?.ToString().Contains("IsUnique()") ?? false;
            if (props.Count > 0)
                _indexes.Add(new IndexInfo(entityName, props, isUnique));
        }
    }

    private void ExtractFluentApiManyToMany(MethodDeclarationSyntax method, List<EntityInfo> entities)
    {
        foreach (var inv in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var invText = inv.ToString();
            if (!invText.Contains("HasMany") || !invText.Contains("WithMany")) continue;

            // Find source entity from Entity<T>()
            string? sourceEntity = null;
            string? targetEntity = null;
            foreach (var generic in inv.DescendantNodes().OfType<GenericNameSyntax>())
            {
                if (generic.Identifier.Text == "Entity" && generic.TypeArgumentList.Arguments.Count > 0)
                    sourceEntity = generic.TypeArgumentList.Arguments[0].ToString();
                if (generic.Identifier.Text == "HasMany" && generic.TypeArgumentList.Arguments.Count > 0)
                    targetEntity = generic.TypeArgumentList.Arguments[0].ToString();
                if (generic.Identifier.Text == "WithMany" && targetEntity == null && generic.TypeArgumentList.Arguments.Count > 0)
                    targetEntity = generic.TypeArgumentList.Arguments[0].ToString();
            }

            if (sourceEntity != null && targetEntity != null)
            {
                var existing = entities.FirstOrDefault(e => e.Name == sourceEntity);
                if (existing != null && !existing.Relationships.Any(r => r.Target == targetEntity && r.Type == "M:N"))
                {
                    existing.Relationships.Add(new RelationshipInfo(targetEntity, "M:N", null, null));
                }
            }
        }
    }

    private void ExtractFluentApiForeignKeys(MethodDeclarationSyntax method, List<EntityInfo> entities)
    {
        foreach (var inv in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var invText = inv.Expression.ToString();
            if (!invText.Contains("HasForeignKey")) continue;

            // Extract FK property name from string or lambda
            string? fkProp = null;
            // String form: HasForeignKey("OrderId")
            foreach (var literal in inv.DescendantNodes().OfType<LiteralExpressionSyntax>())
            {
                fkProp = literal.Token.ValueText;
                break;
            }
            // Lambda form: HasForeignKey(e => e.OrderId)
            if (fkProp == null)
            {
                foreach (var memberAccess in inv.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
                {
                    fkProp = memberAccess.Name.Identifier.Text;
                    break;
                }
            }

            if (fkProp == null) continue;

            // Find the source entity and update the relationship
            string? sourceEntity = null;
            foreach (var ancestor in inv.Ancestors().OfType<InvocationExpressionSyntax>())
            {
                foreach (var generic in ancestor.DescendantNodes().OfType<GenericNameSyntax>())
                {
                    if (generic.Identifier.Text == "Entity" && generic.TypeArgumentList.Arguments.Count > 0)
                    {
                        sourceEntity = generic.TypeArgumentList.Arguments[0].ToString();
                        break;
                    }
                }
                if (sourceEntity != null) break;
            }

            if (sourceEntity != null)
            {
                var entity = entities.FirstOrDefault(e => e.Name == sourceEntity);
                if (entity != null)
                {
                    // Update the last relationship that doesn't have a FK set
                    var rel = entity.Relationships.LastOrDefault(r => r.ForeignKey == null);
                    if (rel != null)
                    {
                        var idx = entity.Relationships.IndexOf(rel);
                        entity.Relationships[idx] = rel with { ForeignKey = fkProp };
                    }
                }
            }
        }
    }

    // ========================================================================
    // Relationship extraction
    // ========================================================================

    private void ExtractFluentApiRelationships(MethodDeclarationSyntax method,
        List<EntityInfo> entities)
    {
        var invocations = method.DescendantNodes().OfType<InvocationExpressionSyntax>();
        foreach (var inv in invocations)
        {
            var text = inv.ToString();
            if (text.Contains("HasOne") || text.Contains("HasMany"))
            {
                foreach (var generic in inv.DescendantNodes().OfType<GenericNameSyntax>())
                {
                    if (generic.Identifier.Text is "HasOne" or "HasMany" or "WithOne" or "WithMany")
                    {
                        var typeArgs = generic.TypeArgumentList.Arguments;
                        if (typeArgs.Count > 0)
                        {
                            var targetEntity = typeArgs[0].ToString();
                            var relType = generic.Identifier.Text.Contains("Many") ? "1:N" : "1:1";

                            var entityCall = inv.Ancestors().OfType<InvocationExpressionSyntax>()
                                .FirstOrDefault(a => a.ToString().Contains("Entity<"));
                            if (entityCall != null)
                            {
                                var sourceGeneric = entityCall.DescendantNodes()
                                    .OfType<GenericNameSyntax>()
                                    .FirstOrDefault(g => g.Identifier.Text == "Entity");
                                if (sourceGeneric?.TypeArgumentList.Arguments.Count > 0)
                                {
                                    var sourceEntity = sourceGeneric.TypeArgumentList.Arguments[0].ToString();
                                    var existing = entities.FirstOrDefault(e => e.Name == sourceEntity);
                                    if (existing != null && !existing.Relationships.Any(r => r.Target == targetEntity))
                                    {
                                        existing.Relationships.Add(new RelationshipInfo(targetEntity, relType, null, null));
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ========================================================================
    // Field extraction
    // ========================================================================

    private List<FieldInfo> ExtractFields(ClassDeclarationSyntax classDecl)
    {
        var fields = new List<FieldInfo>();
        foreach (var prop in classDecl.Members.OfType<PropertyDeclarationSyntax>())
        {
            var name = prop.Identifier.Text;
            var type = prop.Type.ToString();
            bool isKey = name == "Id" || (name.EndsWith("Id") && name.Length > 2);
            bool isNav = type.StartsWith("ICollection") || type.StartsWith("List") ||
                         type.StartsWith("IEnumerable") || type.StartsWith("virtual ");
            bool isRequired = false;
            bool isNotMapped = false;
            string? columnName = null;
            int? maxLen = null;

            foreach (var attrList in prop.AttributeLists)
            {
                foreach (var attr in attrList.Attributes)
                {
                    var attrName = attr.Name.ToString();
                    if (attrName is "Key") isKey = true;
                    if (attrName is "Required") isRequired = true;
                    if (attrName is "NotMapped") isNotMapped = true;
                    if (attrName is "Column" && attr.ArgumentList?.Arguments.Count > 0)
                        columnName = attr.ArgumentList.Arguments[0].ToString().Trim('"');
                    if (attrName is "MaxLength" or "StringLength" && attr.ArgumentList?.Arguments.Count > 0)
                    {
                        if (int.TryParse(attr.ArgumentList.Arguments[0].ToString(), out var len))
                            maxLen = len;
                    }
                }
            }

            if (!isNav && !isNotMapped)
                fields.Add(new FieldInfo(name, type, maxLen, isKey, false, isRequired, columnName));
        }
        return fields;
    }

    private List<RelationshipInfo> ExtractNavigationRelationships(ClassDeclarationSyntax classDecl)
    {
        var rels = new List<RelationshipInfo>();
        foreach (var prop in classDecl.Members.OfType<PropertyDeclarationSyntax>())
        {
            var type = prop.Type.ToString();
            var name = prop.Identifier.Text;

            // Skip [NotMapped] properties
            bool isNotMapped = prop.AttributeLists
                .SelectMany(al => al.Attributes)
                .Any(a => a.Name.ToString() is "NotMapped");
            if (isNotMapped) continue;

            if (type.StartsWith("ICollection<") || type.StartsWith("List<") || type.StartsWith("IEnumerable<"))
            {
                var start = type.IndexOf('<') + 1;
                var end = type.LastIndexOf('>');
                if (start > 0 && end > start)
                {
                    var target = type[start..end];
                    if (!_ownedTypes.Contains(target))
                        rels.Add(new RelationshipInfo(target, "1:N", name, null));
                }
            }
            else if (!type.StartsWith("string") && !type.StartsWith("int") && !type.StartsWith("bool")
                     && !type.StartsWith("decimal") && !type.StartsWith("DateTime") && !type.StartsWith("double")
                     && !type.StartsWith("float") && !type.StartsWith("long") && !type.StartsWith("byte")
                     && !type.StartsWith("Guid") && !type.EndsWith("?") && char.IsUpper(type[0])
                     && !type.Contains("<") && !_ownedTypes.Contains(type))
            {
                rels.Add(new RelationshipInfo(type, "1:1", name, null));
            }
        }
        return rels;
    }

    // ========================================================================
    // Access method extraction
    // ========================================================================

    private void ExtractDataAccessMethods(ClassDeclarationSyntax classDecl,
        SemanticModel model, string file, List<AccessMethodInfo> methods,
        List<StoredProcRef> storedProcs, ref bool dapper, ref bool rawSql,
        HashSet<string> dbSetPropertyNames, Dictionary<string, string> dbSetToEntity)
    {
        var className = classDecl.Identifier.Text;

        foreach (var method in classDecl.Members.OfType<MethodDeclarationSyntax>())
        {
            var methodName = method.Identifier.Text;
            var bodyText = method.Body?.ToString() ?? method.ExpressionBody?.ToString() ?? "";

            var allMarkers = new[] { ".Where(", ".Select(", ".Include(", ".Join(", ".GroupBy(",
                ".FirstOrDefault(", ".SingleOrDefault(", ".ToListAsync(", ".CountAsync(",
                ".SumAsync(", "FromSqlRaw", "FromSqlInterpolated", "ExecuteSqlRaw",
                "ExecuteSqlInterpolatedAsync", "ExecuteSqlRawAsync",
                "SaveChangesAsync", "SaveChanges(",
                ".Query<", ".QueryAsync<", ".Execute(", ".ExecuteAsync(",
                "SqlCommand", "SqlConnection", "SqlDataReader",
                ".FirstOrDefaultAsync(", ".SingleOrDefaultAsync(", ".AnyAsync(",
                ".ThenInclude(",
                "Database.ExecuteSqlRawAsync", "Database.SqlQueryRaw" };

            if (!allMarkers.Any(m => bodyText.Contains(m))) continue;

            var dbSpecificMarkers = new[] {
                ".Include(", ".ThenInclude(",
                ".ToListAsync(", ".ToArrayAsync(",
                ".FirstOrDefaultAsync(", ".FirstAsync(",
                ".SingleOrDefaultAsync(", ".SingleAsync(",
                ".CountAsync(", ".SumAsync(", ".AnyAsync(", ".AllAsync(",
                ".MaxAsync(", ".MinAsync(", ".AverageAsync(",
                "FromSqlRaw", "FromSqlInterpolated",
                "ExecuteSqlRaw", "ExecuteSqlRawAsync",
                "ExecuteSqlInterpolatedAsync",
                "Database.ExecuteSqlRawAsync", "Database.SqlQueryRaw",
                "SaveChangesAsync", "SaveChanges(",
                ".Query<", ".QueryAsync<", ".QueryFirstAsync<",
                ".QueryFirstOrDefaultAsync<", ".QuerySingleAsync<",
                ".QuerySingleOrDefaultAsync<",
                ".Execute(", ".ExecuteAsync(",
                "SqlCommand", "SqlConnection", "SqlDataReader",
            };
            bool isDbQuery = dbSpecificMarkers.Any(m => bodyText.Contains(m));

            if (!isDbQuery && dbSetPropertyNames.Count > 0)
            {
                foreach (var dbSetName in dbSetPropertyNames)
                {
                    if (bodyText.Contains($".{dbSetName}.") || bodyText.Contains($".{dbSetName}\n") ||
                        bodyText.Contains($".{dbSetName})"))
                    {
                        isDbQuery = true;
                        break;
                    }
                }
            }

            // --- Specification pattern detection ---
            // If method accepts ISpecification<T> or calls ApplySpecification, it's a DB query
            if (!isDbQuery)
            {
                var paramTypes = method.ParameterList.Parameters
                    .Select(p => p.Type?.ToString() ?? "").ToList();
                if (paramTypes.Any(t => t.Contains("ISpecification") || t.Contains("Specification")))
                    isDbQuery = true;
                if (bodyText.Contains("ApplySpecification") || bodyText.Contains("GetQuery"))
                    isDbQuery = true;
            }

            var operation = "read";
            if (bodyText.Contains("SaveChangesAsync") || bodyText.Contains("SaveChanges(") ||
                bodyText.Contains("Add(") || bodyText.Contains("AddAsync(") ||
                bodyText.Contains("AddRange(") || bodyText.Contains("AddRangeAsync(") ||
                bodyText.Contains("Update(") || bodyText.Contains("Remove(") ||
                bodyText.Contains("RemoveRange(") ||
                bodyText.Contains("ExecuteSqlRaw") || bodyText.Contains("ExecuteSqlRawAsync") ||
                bodyText.Contains(".Execute(") || bodyText.Contains(".ExecuteAsync("))
                operation = "write";

            // Extract LINQ expressions
            string? linqExpr = null;
            var invocations = method.DescendantNodes().OfType<InvocationExpressionSyntax>().ToList();
            var linqChain = invocations.Where(i =>
            {
                var text = i.Expression.ToString();
                return text.Contains(".Where") || text.Contains(".Select") ||
                       text.Contains(".Include") || text.Contains(".OrderBy") ||
                       text.Contains(".GroupBy") || text.Contains(".Join") ||
                       text.Contains(".FirstOrDefault") || text.Contains(".SingleOrDefault") ||
                       text.Contains(".ToListAsync") || text.Contains(".CountAsync");
            }).ToList();

            if (linqChain.Any())
            {
                var outermost = linqChain.OrderByDescending(i => i.Span.Length).First();
                linqExpr = outermost.ToString();
                if (linqExpr.Length > 500) linqExpr = linqExpr[..500] + "...";
            }

            // Extract entities referenced
            var entities = new HashSet<string>();
            foreach (var inv in invocations)
            {
                foreach (var generic in inv.DescendantNodes().OfType<GenericNameSyntax>())
                {
                    foreach (var typeArg in generic.TypeArgumentList.Arguments)
                    {
                        var typeName = typeArg.ToString();
                        if (char.IsUpper(typeName[0]) && !typeName.Contains("<"))
                            entities.Add(typeName);
                    }
                }
                foreach (var memberAccess in inv.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
                {
                    var memberName = memberAccess.Name.Identifier.Text;
                    // Use the DbSet mapping to resolve entity names accurately
                    // e.g., _context.Orders → Orders is in dbSetToEntity → "Order"
                    if (dbSetToEntity.TryGetValue(memberName, out var entityFromDbSet))
                    {
                        entities.Add(entityFromDbSet);
                    }
                    else if (memberName.Length > 2 && char.IsUpper(memberName[0]) &&
                        (memberName.EndsWith("s") || memberName.EndsWith("es")))
                    {
                        // Fallback singularization for non-DbSet member access (e.g., Dapper)
                        var singular = Singularize(memberName);
                        if (singular.Length > 1) entities.Add(singular);
                    }
                }
            }

            var parameters = method.ParameterList.Parameters
                .Select(p => new ParameterInfo(p.Identifier.Text, p.Type?.ToString() ?? "unknown"))
                .ToList();

            // Detect stored procedure calls — string literals, nameof(), and constants
            foreach (var literal in method.DescendantNodes().OfType<LiteralExpressionSyntax>())
            {
                var val = literal.Token.ValueText;
                if (val.Contains("sp_") || val.Contains("usp_") || val.Contains("EXEC "))
                {
                    storedProcs.Add(new StoredProcRef(val.Trim(), $"{className}.{methodName}", file,
                        literal.GetLocation().GetLineSpan().StartLinePosition.Line + 1));
                }
            }
            // Also check nameof() and const references for stored proc names
            foreach (var nameofExpr in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var exprText = nameofExpr.Expression.ToString();
                if (exprText == "nameof")
                {
                    var arg = nameofExpr.ArgumentList.Arguments.FirstOrDefault()?.ToString() ?? "";
                    if (arg.Contains("sp_") || arg.Contains("usp_"))
                    {
                        storedProcs.Add(new StoredProcRef(arg, $"{className}.{methodName}", file,
                            nameofExpr.GetLocation().GetLineSpan().StartLinePosition.Line + 1));
                    }
                }
            }
            // Detect CommandType.StoredProcedure — the SQL string variable is a sproc name
            // Covers both ADO.NET (cmd.CommandType = StoredProcedure) and Dapper (commandType: StoredProcedure)
            if (bodyText.Contains("StoredProcedure"))
            {
                // Find all string literals in the method — any that are assigned to a sql/command variable
                // and used with StoredProcedure are sproc names
                var stringLiterals = method.DescendantNodes().OfType<LiteralExpressionSyntax>()
                    .Where(l => l.IsKind(Microsoft.CodeAnalysis.CSharp.SyntaxKind.StringLiteralExpression))
                    .Select(l => l.Token.ValueText.Trim())
                    .Where(v => !string.IsNullOrEmpty(v)
                        && !v.Contains(" ")       // Skip SQL statements (they have spaces)
                        && !v.Contains("@")       // Skip parameter names
                        && !v.Contains("=")       // Skip connection strings
                        && !v.StartsWith("api/")  // Skip route templates
                        && !v.StartsWith("/")      // Skip paths
                        && v.Length > 2            // Skip tiny strings
                        && char.IsLetter(v[0]))   // Must start with a letter
                    .ToList();

                foreach (var spName in stringLiterals)
                {
                    // Avoid duplicates from the sp_/usp_ detection above
                    if (!storedProcs.Any(sp => sp.Name == spName && sp.CalledFrom == $"{className}.{methodName}"))
                    {
                        storedProcs.Add(new StoredProcRef(spName, $"{className}.{methodName}", file,
                            method.GetLocation().GetLineSpan().StartLinePosition.Line + 1));
                    }
                }
            }

            // Detect Dapper
            if (bodyText.Contains(".Query<") || bodyText.Contains(".QueryAsync<") ||
                bodyText.Contains("DapperExtensions"))
            {
                dapper = true;
                foreach (var generic in method.DescendantNodes().OfType<GenericNameSyntax>())
                {
                    var genName = generic.Identifier.Text;
                    if (genName is "QueryAsync" or "Query" or "QueryFirstAsync" or "QueryFirstOrDefaultAsync"
                        or "QuerySingleAsync" or "QuerySingleOrDefaultAsync")
                    {
                        foreach (var typeArg in generic.TypeArgumentList.Arguments)
                        {
                            var typeName = typeArg.ToString();
                            if (char.IsUpper(typeName[0]) && !typeName.Contains("<"))
                                entities.Add(typeName);
                        }
                    }
                }
            }

            if (bodyText.Contains("SqlCommand") || bodyText.Contains("SqlConnection") ||
                bodyText.Contains("FromSqlRaw") || bodyText.Contains("Database.SqlQueryRaw"))
                rawSql = true;

            // Extract structured access pattern details from LINQ chains
            var patternDetails = ExtractPatternDetails(method, bodyText, invocations);

            var lineNum = method.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
            methods.Add(new AccessMethodInfo(
                file, className, methodName,
                method.ReturnType.ToString(),
                parameters, linqExpr,
                entities.ToList(), operation,
                new List<string>(),
                lineNum, isDbQuery, patternDetails));
        }
    }

    // ========================================================================
    // Structured access pattern extraction
    // ========================================================================

    private AccessPatternDetails ExtractPatternDetails(MethodDeclarationSyntax method,
        string bodyText, List<InvocationExpressionSyntax> invocations)
    {
        var filterFields = new List<string>();
        var sortFields = new List<string>();
        var includeChains = new List<string>();
        var projectionFields = new List<string>();
        var groupByFields = new List<string>();
        string? aggregation = null;
        bool hasPagination = bodyText.Contains(".Skip(") || bodyText.Contains(".Take(");

        // --- Filter fields from .Where() lambdas ---
        foreach (var inv in invocations)
        {
            var exprText = inv.Expression.ToString();

            // .Where(x => x.Email == email && x.IsActive)
            if (exprText.Contains(".Where"))
            {
                foreach (var lambda in inv.DescendantNodes().OfType<SimpleLambdaExpressionSyntax>())
                {
                    ExtractFieldsFromPredicate(lambda.Body, filterFields);
                }
                foreach (var lambda in inv.DescendantNodes().OfType<ParenthesizedLambdaExpressionSyntax>())
                {
                    ExtractFieldsFromPredicate(lambda.Body, filterFields);
                }
            }

            // .OrderBy(x => x.CreatedDate) / .OrderByDescending(x => x.Name)
            if (exprText.Contains(".OrderBy") || exprText.Contains(".OrderByDescending") ||
                exprText.Contains(".ThenBy") || exprText.Contains(".ThenByDescending"))
            {
                var direction = exprText.Contains("Descending") ? "DESC" : "ASC";
                foreach (var memberAccess in inv.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
                {
                    var fieldName = memberAccess.Name.Identifier.Text;
                    // Skip the LINQ method name itself and lambda parameter
                    if (fieldName is not ("OrderBy" or "OrderByDescending" or "ThenBy" or "ThenByDescending")
                        && char.IsUpper(fieldName[0]))
                    {
                        var sortEntry = $"{fieldName} {direction}";
                        if (!sortFields.Contains(sortEntry))
                            sortFields.Add(sortEntry);
                    }
                }
            }

            // .Include(x => x.Items) / .ThenInclude(x => x.Product)
            if (exprText.Contains(".Include") || exprText.Contains(".ThenInclude"))
            {
                var chain = new List<string>();
                ExtractIncludeChain(inv, chain);
                if (chain.Count > 0)
                {
                    var chainStr = string.Join(".", chain);
                    if (!includeChains.Contains(chainStr))
                        includeChains.Add(chainStr);
                }
            }

            // .Select(x => new { x.Id, x.Name }) or .Select(x => new DTO { Id = x.Id })
            if (exprText.Contains(".Select"))
            {
                foreach (var anon in inv.DescendantNodes().OfType<AnonymousObjectCreationExpressionSyntax>())
                {
                    foreach (var init in anon.Initializers)
                    {
                        var fieldName = init.NameEquals?.Name.Identifier.Text
                            ?? ExtractFieldFromExpression(init.Expression);
                        if (fieldName != null && !projectionFields.Contains(fieldName))
                            projectionFields.Add(fieldName);
                    }
                }
                // Named type projection: new DTO { Id = x.Id, Name = x.Name }
                foreach (var objCreation in inv.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
                {
                    if (objCreation.Initializer != null)
                    {
                        foreach (var expr in objCreation.Initializer.Expressions)
                        {
                            if (expr is AssignmentExpressionSyntax assignment)
                            {
                                var fieldName = assignment.Left.ToString();
                                if (!projectionFields.Contains(fieldName))
                                    projectionFields.Add(fieldName);
                            }
                        }
                    }
                }
            }

            // .GroupBy(x => x.CategoryId)
            if (exprText.Contains(".GroupBy"))
            {
                foreach (var memberAccess in inv.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
                {
                    var fieldName = memberAccess.Name.Identifier.Text;
                    if (fieldName != "GroupBy" && char.IsUpper(fieldName[0]) && !groupByFields.Contains(fieldName))
                        groupByFields.Add(fieldName);
                }
            }
        }

        // --- Aggregation detection ---
        if (bodyText.Contains(".CountAsync(") || bodyText.Contains(".Count("))
            aggregation = "Count";
        else if (bodyText.Contains(".SumAsync(") || bodyText.Contains(".Sum("))
            aggregation = "Sum";
        else if (bodyText.Contains(".AverageAsync(") || bodyText.Contains(".Average("))
            aggregation = "Average";
        else if (bodyText.Contains(".MinAsync(") || bodyText.Contains(".Min("))
            aggregation = "Min";
        else if (bodyText.Contains(".MaxAsync(") || bodyText.Contains(".Max("))
            aggregation = "Max";

        // --- Transaction detection: multiple entity changes before SaveChanges ---
        var changeMarkers = new[] { ".Add(", ".AddAsync(", ".AddRange(", ".Update(", ".Remove(",
            ".RemoveRange(", ".Attach(" };
        int entityChangeCount = changeMarkers.Sum(m =>
        {
            int count = 0; int idx = 0;
            while ((idx = bodyText.IndexOf(m, idx)) != -1) { count++; idx += m.Length; }
            return count;
        });
        bool isTransaction = entityChangeCount > 1 &&
            (bodyText.Contains("SaveChangesAsync") || bodyText.Contains("SaveChanges("));

        return new AccessPatternDetails(
            filterFields.Distinct().ToList(),
            sortFields,
            includeChains,
            projectionFields.Distinct().ToList(),
            groupByFields.Distinct().ToList(),
            aggregation,
            hasPagination,
            isTransaction,
            entityChangeCount
        );
    }

    private void ExtractFieldsFromPredicate(CSharpSyntaxNode body, List<string> fields)
    {
        // Extract field names from binary expressions like x.Email == value, x.IsActive, x.Age > 18
        foreach (var binary in body.DescendantNodesAndSelf().OfType<BinaryExpressionSyntax>())
        {
            ExtractFieldFromSide(binary.Left, fields);
            ExtractFieldFromSide(binary.Right, fields);
        }
        // Also catch simple member access like x.IsActive (boolean check without ==)
        foreach (var memberAccess in body.DescendantNodesAndSelf().OfType<MemberAccessExpressionSyntax>())
        {
            var fieldName = memberAccess.Name.Identifier.Text;
            if (char.IsUpper(fieldName[0]) && !fields.Contains(fieldName)
                && fieldName is not ("HasValue" or "Value" or "Length" or "Count"))
                fields.Add(fieldName);
        }
    }

    private void ExtractFieldFromSide(ExpressionSyntax expr, List<string> fields)
    {
        if (expr is MemberAccessExpressionSyntax memberAccess)
        {
            var fieldName = memberAccess.Name.Identifier.Text;
            // Skip common non-field members and LINQ method names
            if (char.IsUpper(fieldName[0]) && !fields.Contains(fieldName)
                && fieldName is not ("HasValue" or "Value" or "Length" or "Count"
                    or "Where" or "Select" or "Any" or "All" or "Contains"))
                fields.Add(fieldName);
        }
    }

    private string? ExtractFieldFromExpression(ExpressionSyntax expr)
    {
        if (expr is MemberAccessExpressionSyntax memberAccess)
            return memberAccess.Name.Identifier.Text;
        if (expr is IdentifierNameSyntax identifier)
            return identifier.Identifier.Text;
        return null;
    }

    private void ExtractIncludeChain(InvocationExpressionSyntax inv, List<string> chain)
    {
        // Get the navigation property name from the lambda
        foreach (var memberAccess in inv.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
        {
            var name = memberAccess.Name.Identifier.Text;
            if (name is not ("Include" or "ThenInclude") && char.IsUpper(name[0]))
            {
                if (!chain.Contains(name))
                    chain.Add(name);
                break; // Only take the first (the navigation property)
            }
        }
    }
}

// --- Entry point ---
class Program
{
    static int Main(string[] args)
    {
        if (args.Length == 0)
        {
            Console.Error.WriteLine("Usage: SqlToDynamoDbDesignMentorAnalyzer <project-path> [--output <file>]");
            Console.Error.WriteLine("  Analyzes a .NET project using Roslyn and outputs structured JSON.");
            return 1;
        }

        var projectPath = args[0];
        var outputPath = "roslyn_analysis.json";

        for (int i = 1; i < args.Length; i++)
        {
            if (args[i] == "--output" && i + 1 < args.Length)
                outputPath = args[++i];
        }

        if (!Directory.Exists(projectPath))
        {
            Console.Error.WriteLine($"Error: Directory not found: {projectPath}");
            return 1;
        }

        Console.Error.WriteLine($"Analyzing .NET project: {projectPath}");
        var analyzer = new RoslynAnalyzer(projectPath);
        var report = analyzer.Analyze();

        var options = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
        };

        var json = JsonSerializer.Serialize(report, options);
        File.WriteAllText(outputPath, json);

        Console.Error.WriteLine($"Entities: {report.Entities.Count}");
        Console.Error.WriteLine($"Access methods (DB queries): {report.AccessMethods.Count}");
        Console.Error.WriteLine($"Supplementary methods (in-memory): {report.SupplementaryMethods.Count}");
        Console.Error.WriteLine($"Stored procedures: {report.StoredProcedures.Count}");
        Console.Error.WriteLine($"Indexes: {report.Indexes.Count}");
        Console.Error.WriteLine($"EF Core: {report.EfCoreDetected}, Dapper: {report.DapperDetected}, Raw SQL: {report.RawSqlDetected}");
        Console.Error.WriteLine($"Output: {outputPath}");

        Console.WriteLine(json);
        return 0;
    }
}
