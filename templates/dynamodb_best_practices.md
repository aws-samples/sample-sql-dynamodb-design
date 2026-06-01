# DynamoDB Best Practices Knowledge Base

## Single-Table Design Principles
- Use a single table for related entities to minimize API calls and enable transactional operations
- Overload partition and sort keys with entity-type prefixes (e.g., `USER#123`, `ORDER#456`)
- Use item collections (same PK, different SK) for 1:N relationships
- Maximum 5 GSIs per table (soft limit, can be increased but adds cost)
- Each GSI should serve multiple access patterns (overloaded GSIs)

## Key Design Rules
- Partition key must provide even distribution of data and traffic
- Sort key enables range queries within a partition
- Composite sort keys (e.g., `STATUS#DATE#ID`) enable hierarchical queries
- All key values are strings in DynamoDB — numeric values MUST be zero-padded for correct lexicographic sorting

## GSI Projection Optimization
- **KEYS_ONLY**: Lowest storage/write cost. Use when you only need to look up the primary key, then fetch full item from base table
- **INCLUDE**: Project only the attributes needed by the access patterns served by this GSI. Best balance of cost and performance
- **ALL**: Highest storage/write cost. Only use when:
  - The GSI serves access patterns that need most/all attributes
  - The read frequency is very high and a second fetch to base table would be expensive
  - The item size is small (< 1 KB) so storage overhead is minimal
- Default to INCLUDE with specific attributes, NOT ALL
- For each GSI, list which access patterns it serves and which attributes those patterns need
- Document the projection choice rationale

## Expression Rules — STRICT ENFORCEMENT

### KeyConditionExpression (Server-side, efficient — REQUIRED for Query operations)
- Partition key: ONLY `=` operator. No other operator is allowed on partition key.
- Sort key: `=`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `begins_with()`
- NOT supported in KeyConditionExpression: `OR`, `IN`, `NOT`, `CONTAINS`, `contains()`, multiple `begins_with()`, combining `begins_with()` with comparison operators on same sort key
- Pipe syntax `begins_with(SK, 'A|B|C')` does NOT exist in DynamoDB

### FilterExpression — CRITICAL RESTRICTIONS
- **CANNOT contain partition key or sort key attributes.** PK and SK can ONLY appear in KeyConditionExpression, NEVER in FilterExpression. This is a DynamoDB hard constraint.
- **CANNOT use `begins_with(PK, ...)` in FilterExpression.** This is invalid.
- Supports on NON-KEY attributes only: `=`, `<>`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `IN`, `begins_with()`, `contains()`, `attribute_exists()`, `attribute_not_exists()`, `attribute_type()`, `size()`
- Supports `AND`, `OR`, `NOT` logical operators on non-key attributes
- Applied AFTER items are read from the index — still consumes RCUs for ALL scanned items
- Use sparingly — high filter ratios (>50% items filtered out) indicate a missing GSI

### SCAN — NEVER RECOMMEND AS PRIMARY APPROACH
- Scan reads EVERY item in the table — O(N) cost, unacceptable for production workloads
- **NEVER recommend Scan as the primary approach for any access pattern**
- For patterns that seem to require Scan (e.g., text search with `Contains()`), ALWAYS provide a structured analysis:

#### Required structure for patterns that cannot use simple Query:

**Step 1: Show the DynamoDB-native approach FIRST**
- Design GSIs on the searchable attributes
- Show how parallel queries on each GSI + client-side merge handles the pattern
- Document the tradeoffs:
  - Number of additional GSIs required
  - Write amplification cost (each GSI adds WCU per write)
  - `begins_with()` limitation: only matches prefix, not substring (e.g., `begins_with(email, 'john')` works but `contains(email, 'john')` does NOT work in KeyConditionExpression)
  - Client-side merge complexity and latency

**Step 2: Explain WHY DynamoDB-native approach has limitations**
- `contains()` (substring match) is NOT supported in KeyConditionExpression — only in FilterExpression
- FilterExpression with `contains()` still reads ALL items in the partition/index first (full RCU cost)
- For true substring/fuzzy search, DynamoDB has no native efficient solution
- `begins_with()` only works for prefix matching, not arbitrary substring

**Step 3: If OpenSearch is recommended, justify with tradeoffs**
- Show what DynamoDB CAN do (prefix search via `begins_with()` on GSI)
- Show what DynamoDB CANNOT do efficiently (substring search, fuzzy match, relevance scoring)
- Explain the specific gap that requires OpenSearch
- Mark the pattern as migration complexity: **"Hard"** or **"Not Possible (DynamoDB only)"**

**Step 4: Classification for migration challenges**
- If DynamoDB-native GSI approach works fully (prefix matching is sufficient, no external service needed): complexity = "Medium"
- If DynamoDB requires FilterExpression with `contains()` on large datasets but no external service: complexity = "Hard"
- **If pattern requires ANY external service (OpenSearch, ElastiCache, etc.)**: complexity = **"Not Possible (DynamoDB only)"** — this is mandatory. If you recommend OpenSearch, the pattern CANNOT be "Medium" or "Hard" — it MUST be "Not Possible (DynamoDB only)"
- ALWAYS explain in `migration_notes` WHY this classification was chosen

### Client-Side Filtering / Merging
- Required when: aggregating across items, joining data from multiple queries, complex transformations
- For OR conditions across different attributes: query each attribute's GSI independently, merge results client-side
- Document the performance impact: additional latency, memory usage, network transfer
- For multi-query patterns, show how to consolidate results in application code

## Capacity Planning
### Read Capacity Units (RCU)
- 1 RCU = 1 strongly consistent read up to 4 KB
- 1 RCU = 2 eventually consistent reads up to 4 KB (0.5 RCU per eventually consistent read)
- RCU per eventually consistent read = ceil(item_size_kb / 4) * 0.5
  - CRITICAL: ANY item ≤ 4 KB costs 0.5 RCU, NOT 1 RCU. The ceil() rounds up to 1, then multiply by 0.5.
  - Example: 0.5 KB item → ceil(0.5/4) = ceil(0.125) = 1 → 1 * 0.5 = 0.5 RCU
  - Example: 0.9 KB item → ceil(0.9/4) = ceil(0.225) = 1 → 1 * 0.5 = 0.5 RCU
  - Example: 1 KB item → ceil(1/4) = ceil(0.25) = 1 → 1 * 0.5 = 0.5 RCU
  - Example: 3 KB item → ceil(3/4) = ceil(0.75) = 1 → 1 * 0.5 = 0.5 RCU
  - Example: 4 KB item → ceil(4/4) = ceil(1.0) = 1 → 1 * 0.5 = 0.5 RCU
  - Example: 5 KB item → ceil(5/4) = ceil(1.25) = 2 → 2 * 0.5 = 1.0 RCU
  - Example: 6 KB item → ceil(6/4) = ceil(1.5) = 2 → 2 * 0.5 = 1.0 RCU
  - Example: 10 KB item → ceil(10/4) = ceil(2.5) = 3 → 3 * 0.5 = 1.5 RCU
  - Example: 14 KB item → ceil(14/4) = ceil(3.5) = 4 → 4 * 0.5 = 2.0 RCU
  - Example: 20 KB item → ceil(20/4) = ceil(5.0) = 5 → 5 * 0.5 = 2.5 RCU
- WRONG: "0.9 KB → 1 RCU" — this is INCORRECT. 0.9 KB → 0.5 RCU.
- WRONG: "1 KB → 1 RCU" — this is INCORRECT. 1 KB → 0.5 RCU.
- Query reads ALL matching items — RCUs based on total data scanned, not returned
- CRITICAL: Total RCU/hr = RCU_per_read * reads_per_hour (simple multiplication, no halving)
  - Example: RCU/read = 1.0, reads/hr = 30000 → Total RCU/hr = 30,000
  - Example: RCU/read = 0.5, reads/hr = 30000 → Total RCU/hr = 15,000

### Write Capacity Units (WCU)
- 1 WCU = 1 write up to 1 KB
- Items > 1 KB: ceil(item_size_kb / 1) WCUs
- Updates rewrite the ENTIRE item
- GSI writes: each GSI adds WCU cost for every write to the base table (if GSI key attributes change)

### GSI Write Amplification
- Every write to the base table that changes a GSI key or projected attribute triggers a write to that GSI
- With ALL projection: every base table write triggers a GSI write
- With INCLUDE/KEYS_ONLY: only writes that change projected attributes trigger GSI writes
- This is a major cost factor — minimize GSI projections to reduce write amplification

## Entity Modeling Decision Framework
### 1:1 Relationships → Flatten (default)
- Merge into single item unless:
  - Combined size approaches 400 KB
  - One side has significantly different write frequency
  - Different access control requirements
- Calculate: combined_size = parent_bytes + child_bytes + 100 overhead

### 1:N Relationships → Vertical Partitioning (item collection)
- Same PK, different SK prefix
- Fetch parent: `PK = X AND SK = 'METADATA#...'`
- Fetch children: `PK = X AND begins_with(SK, 'CHILD#')`
- Fetch all: `PK = X` (no SK condition), classify by SK prefix in app code
- Consider single-item (list/map) if: avg children < 10-20, always read/written together, total < 400 KB

### N:M Relationships → Adjacency List
- Use inverted index pattern with GSI
- Each relationship stored as a separate item

## Numeric Sort Key Rules
- Integers: zero-pad to 6+ digits (e.g., `QTY#000050`)
- Decimals: multiply to integer, then zero-pad (e.g., rating 4.5 → `RATING#0450`)
- Never use raw decimals in keys (`RATING#4.5` breaks sorting)
- All threshold values in expressions must use same format

## C# AWS SDK for DynamoDB
- Use `Amazon.DynamoDBv2` and `Amazon.DynamoDBv2.DocumentModel` namespaces
- `AmazonDynamoDBClient` for low-level API
- `Table.LoadTable()` and `Table.Query()` for document model
- `QueryRequest` with `KeyConditionExpression` for query operations
- `BatchGetItemRequest` for batch reads
- Use `ExpressionAttributeNames` for reserved words (e.g., `#status` for `status`)
- Use `ExpressionAttributeValues` with `AttributeValue` objects

## Cost Optimization
- On-demand: $1.25/million WCU, $0.25/million RCU (us-east-1)
- Provisioned: $0.00065/WCU-hour, $0.00013/RCU-hour
- Use on-demand for unpredictable workloads, provisioned for steady-state
- DAX (DynamoDB Accelerator) for read-heavy, latency-sensitive patterns
- Consider DynamoDB Streams + Lambda for computed aggregations instead of scan-based queries
