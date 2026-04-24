"""
graphql_parser.py
Parses GraphQL schemas (via introspection endpoint or .graphql SDL file) into
an operation list that the script generator understands.
Public functions:
    parse_graphql_introspection(url, headers)  -> list[dict]
    parse_graphql_schema(schema_text)          -> list[dict]
    graphql_operations_to_plain_text(ops)      -> str
"""

import re
import requests


# Full introspection query — asks for all queries, mutations, subscriptions
_INTROSPECTION_QUERY = """
{
  __schema {
    queryType        { name }
    mutationType     { name }
    subscriptionType { name }
    types {
      kind
      name
      fields(includeDeprecated: false) {
        name
        description
        args {
          name
          type { kind name ofType { kind name ofType { kind name } } }
        }
        type { kind name ofType { kind name ofType { kind name } } }
      }
    }
  }
}
"""


def parse_graphql_introspection(url: str, headers: dict = None) -> list[dict]:
    """
    Fetch the GraphQL schema via an introspection query and return a flat list
    of operations (queries, mutations, subscriptions).
    """
    headers = headers or {"Content-Type": "application/json"}
    resp = requests.post(
        url,
        json={"query": _INTROSPECTION_QUERY},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()

    if "errors" in body:
        raise ValueError(f"GraphQL introspection returned errors: {body['errors']}")

    schema = body.get("data", {}).get("__schema", {})
    if not schema:
        raise ValueError("Introspection response missing __schema. Is this a GraphQL endpoint?")

    return _extract_from_introspection(schema)


def parse_graphql_schema(schema_text: str) -> list[dict]:
    """
    Parse a GraphQL SDL schema string (.graphql file content) and extract
    Query / Mutation / Subscription operations.
    """
    operations = []
    for op_type in ("Query", "Mutation", "Subscription"):
        m = re.search(rf'type\s+{op_type}\s*\{{([^}}]+)\}}', schema_text, re.DOTALL)
        if m:
            operations.extend(_parse_sdl_fields(m.group(1), op_type))
    return operations


def graphql_operations_to_plain_text(operations: list[dict]) -> str:
    """Convert the operations list into plain English for the script generator."""
    lines = ["GraphQL API operations:"]
    for op in operations:
        args = ", ".join(f"{a['name']}: {a['type']}" for a in op.get("args", []))
        line = f"  {op['operation_type'].upper()} {op['name']}"
        if args:
            line += f"({args})"
        line += f" -> {op['return_type']}"
        if op.get("description"):
            line += f"  # {op['description']}"
        lines.append(line)
    return "\n".join(lines)


# ── internal helpers ──────────────────────────────────────────────────────────

def _resolve_type(t: dict) -> str:
    if not t:
        return "Any"
    if t.get("name"):
        return t["name"]
    if t.get("ofType"):
        return _resolve_type(t["ofType"])
    return t.get("kind", "Any")


def _extract_from_introspection(schema: dict) -> list[dict]:
    query_type    = (schema.get("queryType")        or {}).get("name", "Query")
    mutation_type = (schema.get("mutationType")     or {}).get("name")
    sub_type      = (schema.get("subscriptionType") or {}).get("name")

    type_map = {
        t["name"]: t
        for t in schema.get("types", [])
        if t.get("kind") == "OBJECT" and not t["name"].startswith("__")
    }

    operations = []
    root_map = {
        query_type:    "Query",
        mutation_type: "Mutation",
        sub_type:      "Subscription",
    }

    for type_name, op_label in root_map.items():
        if not type_name or type_name not in type_map:
            continue
        for field in type_map[type_name].get("fields") or []:
            args = [
                {"name": a["name"], "type": _resolve_type(a.get("type", {}))}
                for a in (field.get("args") or [])
            ]
            operations.append({
                "operation_type": op_label,
                "name":          field["name"],
                "description":   field.get("description") or "",
                "args":          args,
                "return_type":   _resolve_type(field.get("type", {})),
            })

    return operations


def _parse_sdl_fields(block: str, op_type: str) -> list[dict]:
    """Parse field definitions from a type block in SDL format."""
    ops = []
    for m in re.finditer(r'(\w+)\s*(\([^)]*\))?\s*:\s*([\w!\[\]]+)', block):
        name, args_str, return_type = m.groups()
        args = []
        if args_str:
            for am in re.finditer(r'(\w+)\s*:\s*([\w!\[\]]+)', args_str):
                args.append({"name": am.group(1), "type": am.group(2)})
        ops.append({
            "operation_type": op_type,
            "name":          name,
            "description":   "",
            "args":          args,
            "return_type":   return_type,
        })
    return ops
