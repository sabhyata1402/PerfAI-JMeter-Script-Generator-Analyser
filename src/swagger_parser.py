"""
swagger_parser.py
Parses a Swagger / OpenAPI spec (URL or dict) into a flat list of endpoints.
Also parses gRPC .proto files into a service/method list.
Public functions:
    parse_swagger(source: str | dict) -> list[dict]
    parse_proto(source: str)          -> list[dict]
    proto_to_plain_text(services)     -> str
"""

import re
import requests
import yaml
import json


def parse_swagger(source: str | dict) -> list[dict]:
    """
    Parse a Swagger/OpenAPI spec from a URL, file path, or already-loaded dict.

    Returns a list of endpoint dicts:
        [
          {
            "method": "GET",
            "path": "/users/{id}",
            "summary": "Get user by ID",
            "parameters": [...],
            "request_body": {...} | None,
          },
          ...
        ]
    """
    spec = _load_spec(source)
    return _extract_endpoints(spec)


# ── internal helpers ──────────────────────────────────────────────────────────

def _load_spec(source: str | dict) -> dict:
    if isinstance(source, dict):
        return source

    # Try as URL
    if source.startswith("http://") or source.startswith("https://"):
        response = requests.get(source, timeout=10)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "yaml" in content_type or source.endswith((".yaml", ".yml")):
            return yaml.safe_load(response.text)
        return response.json()

    # Try as local file path
    with open(source, "r") as f:
        if source.endswith((".yaml", ".yml")):
            return yaml.safe_load(f)
        return json.load(f)


def _extract_endpoints(spec: dict) -> list[dict]:
    endpoints = []
    paths = spec.get("paths", {})

    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for path, path_item in paths.items():
        # Shared parameters defined at path level
        path_params = path_item.get("parameters", [])

        for method, operation in path_item.items():
            if method.lower() not in http_methods:
                continue
            if not isinstance(operation, dict):
                continue

            # Merge path-level params with operation-level params
            op_params = operation.get("parameters", [])
            all_params = {p.get("name"): p for p in path_params}
            all_params.update({p.get("name"): p for p in op_params})

            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": operation.get("summary", ""),
                "description": operation.get("description", ""),
                "parameters": list(all_params.values()),
                "request_body": _extract_request_body(operation),
                "responses": list(operation.get("responses", {}).keys()),
            })

    return endpoints


def _extract_request_body(operation: dict) -> dict | None:
    body = operation.get("requestBody", {})
    if not body:
        return None
    content = body.get("content", {})
    for media_type, media_obj in content.items():
        schema = media_obj.get("schema", {})
        return {
            "media_type": media_type,
            "schema": schema,
        }
    return None


def parse_proto(source: str) -> list[dict]:
    """
    Parse a gRPC .proto file (path or raw text) and extract services and their RPC methods.

    Returns a list of service/method dicts:
        [
          {
            "service": "UserService",
            "method": "GetUser",
            "input_type": "GetUserRequest",
            "output_type": "GetUserResponse",
            "client_streaming": False,
            "server_streaming": False,
          },
          ...
        ]
    """
    # Load from file path if it looks like one
    if "\n" not in source and (source.endswith(".proto") or "/" in source or "\\" in source):
        with open(source, "r") as f:
            proto_text = f.read()
    else:
        proto_text = source

    return _parse_proto_text(proto_text)


def proto_to_plain_text(services: list[dict]) -> str:
    """Convert the parsed proto service list into plain English for the script generator."""
    lines = ["gRPC API services:"]
    for s in services:
        streaming = ""
        if s.get("client_streaming") and s.get("server_streaming"):
            streaming = " [bidirectional streaming]"
        elif s.get("client_streaming"):
            streaming = " [client streaming]"
        elif s.get("server_streaming"):
            streaming = " [server streaming]"
        lines.append(
            f"  {s['service']}.{s['method']}({s['input_type']}) -> {s['output_type']}{streaming}"
        )
    return "\n".join(lines)


def _parse_proto_text(text: str) -> list[dict]:
    """Extract RPC definitions from proto3 source text."""
    results = []
    # Find each service block
    for svc_match in re.finditer(r'service\s+(\w+)\s*\{([^}]+)\}', text, re.DOTALL):
        service_name = svc_match.group(1)
        body = svc_match.group(2)
        # Find each rpc inside the service block
        for rpc_match in re.finditer(
            r'rpc\s+(\w+)\s*\(\s*(stream\s+)?(\w+)\s*\)\s*returns\s*\(\s*(stream\s+)?(\w+)\s*\)',
            body,
        ):
            method        = rpc_match.group(1)
            client_stream = rpc_match.group(2) is not None
            input_type    = rpc_match.group(3)
            server_stream = rpc_match.group(4) is not None
            output_type   = rpc_match.group(5)
            results.append({
                "service":          service_name,
                "method":           method,
                "input_type":       input_type,
                "output_type":      output_type,
                "client_streaming": client_stream,
                "server_streaming": server_stream,
            })
    return results


def endpoints_to_plain_text(endpoints: list[dict]) -> str:
    """Convert parsed endpoints to a concise plain-text summary for the Claude prompt."""
    lines = []
    for ep in endpoints:
        line = f"{ep['method']} {ep['path']}"
        if ep["summary"]:
            line += f" — {ep['summary']}"
        if ep["parameters"]:
            param_names = [p.get("name", "") for p in ep["parameters"]]
            line += f" (params: {', '.join(param_names)})"
        if ep["request_body"]:
            line += f" [body: {ep['request_body']['media_type']}]"
        lines.append(line)
    return "\n".join(lines)
