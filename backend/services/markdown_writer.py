"""Utility for appending user-added patterns to access_patterns.md."""

import os

MD_FILENAME = "access_patterns.md"
MD_HEADER = "# Access Patterns\n"


def append_pattern_to_md(pattern_data: dict, pattern_type: str = "access") -> None:
    """Append a single pattern to access_patterns.md in extractor format.

    Creates the file with a header if it doesn't exist.

    Args:
        pattern_data: Dict with pattern fields (pattern_id, name, operation,
            source_entities/target_entities, requests_per_hour,
            avg_items_returned/items_per_transaction, source_code).
        pattern_type: "access" or "write".
    """
    if not os.path.exists(MD_FILENAME):
        with open(MD_FILENAME, "w", encoding="utf-8") as f:
            f.write(MD_HEADER)

    md = _format_pattern_md(pattern_data, pattern_type)

    with open(MD_FILENAME, "a", encoding="utf-8") as f:
        f.write(md)


def _format_pattern_md(pattern_data: dict, pattern_type: str = "access") -> str:
    """Format a pattern dict into the extractor's markdown format.

    Returns the markdown string (with leading newline for appending).
    """
    pid = pattern_data.get("pattern_id", "AP-000")
    name = pattern_data.get("name", "")
    operation = pattern_data.get("operation", "READ" if pattern_type == "access" else "WRITE")
    source = pattern_data.get("source", "User-added")
    source_code = pattern_data.get("source_code")

    if pattern_type == "access":
        entities = pattern_data.get("source_entities", [])
        freq = pattern_data.get("requests_per_hour", 0)
        avg_items = pattern_data.get("avg_items_returned", 1)
    else:
        entities = pattern_data.get("target_entities", [])
        freq = pattern_data.get("requests_per_hour", 0)
        avg_items = pattern_data.get("items_per_transaction", 1)

    entities_str = ", ".join(entities) if entities else ""

    lines = [
        "",
        f"#### {pid}: {name}",
        f"- **Source**: {source}",
        f"- **Operation**: {operation}",
        f"- **Description**: {name}",
        f"- **Entities**: {entities_str}",
        f"- **Frequency**: {freq} req/hr",
    ]

    if pattern_type == "access":
        lines.append(f"- **Avg Items Returned**: {avg_items}")
    else:
        lines.append(f"- **Items Per Transaction**: {avg_items}")

    if source_code:
        lines.append("- **Source Code**:")
        lines.append("```sql")
        lines.append(source_code)
        lines.append("```")

    lines.append("")
    return "\n".join(lines)
