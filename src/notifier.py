"""
notifier.py
Sends test completion notifications to Slack and/or Microsoft Teams.
Public functions:
    notify_slack(webhook_url, message, findings=None)  -> bool
    notify_teams(webhook_url, message, findings=None)  -> bool
"""

import json
import requests


def notify_slack(webhook_url: str, message: str, findings: list[dict] = None) -> bool:
    """
    Post a notification to a Slack Incoming Webhook.

    Args:
        webhook_url: Slack Incoming Webhook URL
        message: Summary message (plain text)
        findings: Optional list of AI finding dicts to include as blocks

    Returns:
        True on success, raises RuntimeError on failure.
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "PerfAI — Load Test Complete"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        },
    ]

    if findings:
        severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        for f in findings[:5]:  # cap at 5 to avoid oversized payloads
            sev = (f.get("severity") or "medium").lower()
            emoji = severity_emoji.get(sev, "•")
            ftype = (f.get("type") or "").upper()
            title = f.get("title", "Finding")
            desc = f.get("description", "")[:200]
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{emoji} *[{ftype}]* {title}\n{desc}",
                    },
                }
            )

    payload = {"blocks": blocks}

    resp = requests.post(
        webhook_url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Slack notification failed: {resp.status_code} — {resp.text}"
        )
    return True


def notify_teams(webhook_url: str, message: str, findings: list[dict] = None) -> bool:
    """
    Post a notification to a Microsoft Teams Incoming Webhook (Connector card format).

    Args:
        webhook_url: Teams Incoming Webhook URL
        message: Summary message
        findings: Optional list of AI finding dicts

    Returns:
        True on success, raises RuntimeError on failure.
    """
    severity_color = {"critical": "FF0000", "high": "FF6600", "medium": "FFCC00", "low": "36A64F"}

    facts = []
    if findings:
        for f in findings[:5]:
            sev = (f.get("severity") or "medium").lower()
            ftype = (f.get("type") or "finding").capitalize()
            title = f.get("title", "Finding")
            facts.append({"name": f"[{ftype}]", "value": title})

    sections = [
        {
            "activityTitle": "PerfAI — Load Test Complete",
            "activitySubtitle": message,
            "facts": facts,
            "markdown": True,
        }
    ]

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": severity_color.get(
            _dominant_severity(findings), "7C3AED"
        ),
        "summary": "PerfAI Load Test Complete",
        "sections": sections,
    }

    resp = requests.post(
        webhook_url,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(
            f"Teams notification failed: {resp.status_code} — {resp.text}"
        )
    return True


def _dominant_severity(findings: list[dict] | None) -> str:
    """Return highest severity found across all findings."""
    if not findings:
        return "low"
    order = ["critical", "high", "medium", "low"]
    severities = {(f.get("severity") or "medium").lower() for f in findings}
    for s in order:
        if s in severities:
            return s
    return "low"
