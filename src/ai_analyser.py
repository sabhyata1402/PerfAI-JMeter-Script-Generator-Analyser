"""
ai_analyser.py
Sends parsed JMeter metrics to Azure OpenAI and gets structured performance findings.
Public function: analyse(metrics: dict) -> dict
"""

import json
import os
from openai import AzureOpenAI
from src.results_parser import metrics_to_summary_text


def analyse(metrics: dict) -> dict:
    """
    Send performance metrics to Azure OpenAI and get structured analysis back.

    Returns:
    {
        "verdict":   "pass" | "warning" | "fail",
        "headline":  "One-sentence summary",
        "findings": [
            {
                "type":        "bottleneck" | "strength" | "warning" | "recommendation",
                "title":       "Short title",
                "description": "Detailed explanation",
                "endpoint":    "POST /orders" | None,
                "severity":    "high" | "medium" | "low" | None,
            },
            ...
        ],
        "next_steps": ["Step 1", "Step 2", ...]
    }
    """
    metrics_text = metrics_to_summary_text(metrics)
    prompt = _build_prompt(metrics_text)

    client = _build_client()
    deployment = _get_deployment()
    message = client.chat.completions.create(
        model=deployment,
        temperature=0,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = (message.choices[0].message.content or "").strip()
    return _parse_response(raw)


# -- internal helpers ----------------------------------------------------------

def _build_prompt(metrics_text: str) -> str:
    return f"""You are a senior performance engineer with 15 years of experience analysing JMeter load test results.

Analyse the following JMeter test results and provide a structured performance assessment.

{metrics_text}

Provide your analysis as a JSON object with this exact structure:
{{
  "verdict": "pass" | "warning" | "fail",
  "headline": "One clear sentence summarising the overall result",
  "findings": [
    {{
      "type": "bottleneck" | "strength" | "warning" | "recommendation",
      "title": "Short title (max 8 words)",
      "description": "Detailed explanation with root cause and context (2-4 sentences)",
      "endpoint": "HTTP_METHOD /path or null if not endpoint-specific",
      "severity": "high" | "medium" | "low" | null
    }}
  ],
  "next_steps": [
    "Concrete, actionable next step 1",
    "Concrete, actionable next step 2",
    "Concrete, actionable next step 3"
  ]
}}

Rules for your analysis:
- A finding is a "bottleneck" if it identifies a specific performance problem (e.g. slow endpoint, error spike, DB lock contention)
- A finding is a "strength" if something is performing well and worth noting
- A finding is a "warning" if something is approaching a limit but not yet failing
- A finding is a "recommendation" if you suggest a specific improvement
- Include 4-6 findings total
- Be specific: name the endpoint, name the likely root cause (DB lock, connection pool, N+1 query, etc.)
- Each finding description should include the observed metric, likely impact, and a concrete fix when possible
- Prefer short paragraphs with numbers over generic statements
- "verdict" is "fail" if error rate > 5% or p99 > 3000ms; "warning" if error rate > 1% or p99 > 1500ms; else "pass"
- next_steps should be immediately actionable by a developer (specific, not generic)

Output ONLY the JSON. No markdown, no explanation, no code fences.
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


def _parse_response(raw: str) -> dict:
    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return a safe error structure
        return {
            "verdict": "warning",
            "headline": "Analysis could not be fully parsed — raw output available.",
            "findings": [
                {
                    "type": "warning",
                    "title": "Analysis parsing error",
                    "description": raw[:500],
                    "endpoint": None,
                    "severity": "low",
                }
            ],
            "next_steps": ["Review the raw AI output above", "Re-run the analysis"],
        }
