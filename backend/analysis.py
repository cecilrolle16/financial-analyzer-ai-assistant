"""Turn a model reply into a stable review of any financial document."""

import json
import re

DISCLAIMER = (
    "This is general information from an automated review of the uploaded document. "
    "It is not financial, tax, legal, or investment advice. Check the original document "
    "and talk with a qualified professional before you act on it."
)

SYSTEM_PROMPT = """You review financial documents of every common kind.
Examples include bank statements, credit-card statements, pay stubs, invoices, bills,
receipts, tax forms, loan agreements, insurance documents, and investment statements.
Judge each file by what it actually is. Do not assume it is one particular document.

Rules:
- Use only facts that appear in the document. Do not invent amounts, dates, names, or problems.
- If a figure is not shown, leave it out.
- A problem must be something a careful reader should notice, such as a past-due amount,
  a fee, a negative balance, an unusually large charge, a high interest rate, totals that
  do not match, missing pages or fields, or a term that needs attention.
- If nothing like that is visible, return an empty problems list.
- Recommendations are practical next steps in plain language.
- Never give personalized financial, tax, legal, or investment advice.
- Do not repeat a full account number. If you mention one, show only the last four digits.
- Return JSON only. No markdown.
"""

USER_PROMPT = """Review this financial document and return JSON with exactly these fields:
{
  "documentType": "short name of the document you see",
  "summary": "what this document says, in plain language, 2 to 4 sentences",
  "keyFigures": [{"label": "name of the figure", "value": "the figure as printed"}],
  "problems": [{"severity": "high or medium or low", "title": "short label", "detail": "why it matters"}],
  "recommendations": ["a specific next step the reader can take"]
}
"""

_SEVERITIES = {"high", "medium", "low"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_model_output(raw):
    """Normalize model text into the review the website displays."""
    data = _load_json(raw)
    summary = _clip(data.get("summary"), 1200)
    if not summary:
        summary = (
            "The document was received, but a clear summary could not be read from it. "
            "Try a PDF with selectable text or a clearer scan."
        )
    return {
        "documentType": _clip(data.get("documentType"), 80) or "Financial document",
        "summary": summary,
        "keyFigures": _figures(data.get("keyFigures")),
        "problems": _problems(data.get("problems")),
        "recommendations": _recommendations(data.get("recommendations")),
        "disclaimer": DISCLAIMER,
    }


def _load_json(raw):
    if not isinstance(raw, str):
        return {}
    cleaned = _FENCE.sub("", raw.strip())
    try:
        loaded = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _clip(value, limit):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _figures(items):
    found = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label = _clip(item.get("label"), 80)
        value = _clip(item.get("value"), 80)
        if label and value:
            found.append({"label": label, "value": value})
        if len(found) == 12:
            break
    return found


def _problems(items):
    found = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = _clip(item.get("title"), 120)
        detail = _clip(item.get("detail"), 500)
        severity = _clip(item.get("severity"), 10).lower()
        if severity not in _SEVERITIES:
            severity = "medium"
        if title and detail:
            found.append({"severity": severity, "title": title, "detail": detail})
        if len(found) == 8:
            break
    return found


def _recommendations(items):
    found = []
    for item in items or []:
        text = _clip(item, 300)
        if text:
            found.append(text)
        if len(found) == 8:
            break
    return found
