"""
script_generator.py
Uses Azure OpenAI to generate load test scripts.
Public functions:
    generate_script(endpoints_text, config)         -> str  (JMeter JMX XML)
    generate_gatling_script(endpoints_text, config) -> str  (Gatling Scala)
    generate_k6_script(endpoints_text, config)      -> str  (k6 JavaScript)
"""

import os
import xml.etree.ElementTree as ET
from openai import AzureOpenAI


MAX_GENERATION_ATTEMPTS = 3
MAX_OUTPUT_TOKENS = 16000


def generate_script(endpoints_text: str, config: dict) -> str:
    """
    Ask Azure OpenAI to generate a JMeter JMX script for the given API endpoints.

    Args:
        endpoints_text: Plain-text list of endpoints (from swagger_parser or user input)
        config: dict with keys:
            - virtual_users (int)
            - duration_seconds (int)
            - ramp_up_seconds (int)
            - think_time_ms (int)
            - base_url (str)
            - auth_type (str): "none" | "bearer" | "basic"

    Returns:
        JMX XML string ready to save as .jmx and run with JMeter.
    """
    base_prompt = _build_prompt(endpoints_text, config)
    client = _build_client()
    deployment = _get_deployment()

    last_error = ""

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        prompt = base_prompt if attempt == 1 else _build_retry_prompt(base_prompt, last_error, attempt)

        message = client.chat.completions.create(
            model=deployment,
            temperature=0,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You output only complete, valid JMeter JMX XML. "
                        "Never output partial XML, markdown, or explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

        raw = (message.choices[0].message.content or "").strip()
        if not raw:
            last_error = "Model returned an empty response."
            continue

        xml_text = _extract_xml(raw)

        try:
            _validate_jmx(xml_text, config)
            return xml_text
        except ValueError as exc:
            last_error = str(exc)

    raise RuntimeError(
        "Failed to generate a valid JMX file after 3 attempts. "
        f"Last validation error: {last_error}"
    )


def generate_gatling_script(endpoints_text: str, config: dict) -> str:
    """
    Ask Azure OpenAI to generate a Gatling Scala simulation for the given API.

    Returns:
        Gatling Scala simulation source code as a string.
    """
    prompt = _build_gatling_prompt(endpoints_text, config)
    client = _build_client()
    deployment = _get_deployment()

    message = client.chat.completions.create(
        model=deployment,
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Gatling performance engineer. "
                    "Output only complete, compilable Gatling Scala simulation code. "
                    "Never output markdown fences or explanations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = (message.choices[0].message.content or "").strip()
    # Strip markdown fences if model wraps in code blocks
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines).strip()
    return raw


def generate_k6_script(endpoints_text: str, config: dict) -> str:
    """
    Ask Azure OpenAI to generate a k6 JavaScript test script for the given API.

    Returns:
        k6 JavaScript source code as a string.
    """
    prompt = _build_k6_prompt(endpoints_text, config)
    client = _build_client()
    deployment = _get_deployment()

    message = client.chat.completions.create(
        model=deployment,
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert k6 performance engineer. "
                    "Output only complete, runnable k6 JavaScript. "
                    "Never output markdown fences or explanations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = (message.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines).strip()
    return raw


# -- internal helpers ----------------------------------------------------------

def _build_prompt(endpoints_text: str, config: dict) -> str:
    auth_type = str(config.get("auth_type", "none"))

    return f"""You are an expert JMeter performance engineer with 10+ years of experience.

Generate a complete, production-ready JMeter JMX test plan for the following API.

## API Endpoints
{endpoints_text}

## Load Test Configuration
- Virtual Users (threads): {config.get('virtual_users', 100)}
- Test Duration: {config.get('duration_seconds', 300)} seconds
- Ramp-Up Period: {config.get('ramp_up_seconds', 60)} seconds
- Think Time between requests: {config.get('think_time_ms', 500)} ms
- Base URL: {config.get('base_url', 'https://api.example.com')}
- Authentication: {auth_type}

## Hard Constraints (must follow exactly)
1. Output MUST be complete, well-formed XML from `<?xml ...?>` through final `</jmeterTestPlan>`.
2. In HTTP Request Defaults, split URL into separate fields:
   - `HTTPSampler.domain` must be hostname only (never `http://` or `https://`)
   - `HTTPSampler.protocol` must be `http` or `https`
   - `HTTPSampler.port` must be numeric when applicable
3. Never reference undefined variables.
4. If auth_type is `none`, do NOT include Authorization header.
5. If auth_type is `bearer` and using `${{AUTH_TOKEN}}`, define AUTH_TOKEN in TestPlan user-defined variables.
6. Keep XML concise and avoid unnecessary GUI metadata to reduce output size.

## Requirements for the JMX script
1. Use ThreadGroup with configured users/ramp-up/duration
2. Add HTTP Request Defaults
3. Add Cookie Manager and Cache Manager
4. Add HTTP Header Manager with Content-Type: application/json
5. Add each endpoint as an HTTP Sampler with sensible name
6. For POST/PUT endpoints, add realistic placeholder JSON body
7. Add Constant Timer using think time
8. Add Response Assertions for success status codes
9. Add Summary Report and Simple Data Writer listeners writing to results.jtl
10. Add JMeter properties/variables for parameterisation

## Token Budget
- Keep the XML concise. Omit GUI metadata attributes (testname, enabled, etc.) where not required.
- Do NOT add comments inside XML.
- If the endpoint list is long, group similar endpoints under one HTTP Sampler using variables rather than duplicating sampler blocks.

Output ONLY raw JMX XML. No markdown, no comments, no explanation.
Start exactly with: <?xml version="1.0" encoding="UTF-8"?>
End exactly with: </jmeterTestPlan>
"""


def _build_retry_prompt(base_prompt: str, validation_error: str, attempt: int) -> str:
    return (
        f"{base_prompt}\n\n"
        f"Retry attempt {attempt}. Previous output failed validation: {validation_error}\n"
        "Regenerate the entire JMX from scratch as one complete XML document.\n"
        "Do not truncate. Ensure the document ends with </jmeterTestPlan>."
    )


def _build_gatling_prompt(endpoints_text: str, config: dict) -> str:
    return f"""You are an expert Gatling performance engineer.

Generate a complete, production-ready Gatling Scala simulation for the following API.

## API Endpoints
{endpoints_text}

## Load Test Configuration
- Virtual Users: {config.get('virtual_users', 100)}
- Test Duration: {config.get('duration_seconds', 300)} seconds
- Ramp-Up Period: {config.get('ramp_up_seconds', 60)} seconds
- Think Time: {config.get('think_time_ms', 500)} ms
- Base URL: {config.get('base_url', 'https://api.example.com')}
- Authentication: {config.get('auth_type', 'none')}

## Requirements
1. Use Gatling DSL with a proper simulation class extending Simulation
2. Configure httpProtocol with the base URL and Accept/Content-Type headers
3. Define a scenario covering all endpoints in logical order
4. Use rampUsers during ramp-up, then constantUsersPerSec for steady state
5. Add pause() between requests matching the think time
6. Add response status assertions (status 200 range)
7. Include realistic placeholder JSON bodies for POST/PUT requests
8. Use proper package imports (io.gatling.core.Predef._, io.gatling.http.Predef._)

Output ONLY raw Scala code. Start with the package/import lines. No markdown.
"""


def _build_k6_prompt(endpoints_text: str, config: dict) -> str:
    return f"""You are an expert k6 performance engineer.

Generate a complete, production-ready k6 JavaScript test script for the following API.

## API Endpoints
{endpoints_text}

## Load Test Configuration
- Virtual Users: {config.get('virtual_users', 100)}
- Test Duration: {config.get('duration_seconds', 300)} seconds
- Ramp-Up Period: {config.get('ramp_up_seconds', 60)} seconds
- Think Time: {config.get('think_time_ms', 500)} ms
- Base URL: {config.get('base_url', 'https://api.example.com')}
- Authentication: {config.get('auth_type', 'none')}

## Requirements
1. Export a default function and an options object
2. Configure stages in options.stages for ramp-up then steady state
3. Call each endpoint as an http request with proper method and headers
4. Add sleep() between requests matching the think time (in seconds)
5. Add check() assertions for HTTP status codes
6. Include realistic placeholder JSON bodies for POST/PUT requests
7. Use __ENV variables for base URL and auth token (BASE_URL, AUTH_TOKEN)
8. Add thresholds in options for p(95) < 500ms and error rate < 1%

Output ONLY raw JavaScript. Start with the import lines. No markdown.
"""


def _build_client() -> AzureOpenAI:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

    if not api_key or not endpoint:
        raise ValueError(
            "Missing Azure OpenAI configuration. Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT."
        )

    return AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version)


def _get_deployment() -> str:
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        raise ValueError("Missing AZURE_OPENAI_DEPLOYMENT. Set it to your Azure model deployment name.")
    return deployment


def _extract_xml(raw: str) -> str:
    """Strip markdown code fences if present and normalize surrounding whitespace."""
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        raw = "\n".join(lines)
    return raw.strip()


def _validate_jmx(xml_text: str, config: dict) -> None:
    if not xml_text.startswith("<?xml"):
        raise ValueError("XML declaration is missing at the top of the JMX output.")

    if not xml_text.strip().endswith("</jmeterTestPlan>"):
        raise ValueError("JMX output is truncated or missing closing </jmeterTestPlan> tag.")

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"JMX XML is not well-formed: {exc}") from exc

    if root.tag != "jmeterTestPlan":
        raise ValueError("Root tag is not <jmeterTestPlan>.")

    # Guard against BlazeMeter rejection from unresolved token in no-auth runs.
    if "${AUTH_TOKEN}" in xml_text and str(config.get("auth_type", "none")) == "none":
        raise ValueError("JMX references ${AUTH_TOKEN} even though auth_type is none.")

    # Guard against invalid domain format (must be hostname only).
    if "<stringProp name=\"HTTPSampler.domain\">http" in xml_text:
        raise ValueError("HTTPSampler.domain contains a full URL; it must be hostname only.")
