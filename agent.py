"""Agentic AI assistant for the notebook.

Two modes, both exposed on the right-hand panel:

1. **Deterministic** (default, *no API key needed*) — a rule-based reasoning
   engine that diagnoses the error, explains the root cause in plain language,
   and proposes a concrete fix. Covers the common Python and AIDL errors.

2. **LLM** (*optional, bring your own key*) — when the user supplies an OpenAI
   or Gemini key (or one is configured server-side) the same context is sent to
   the model for a richer, free-form explanation. Falls back to deterministic
   mode automatically if the call fails or no key is present.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

import urllib.request

# --------------------------------------------------------------------------
#  Deterministic knowledge base
# --------------------------------------------------------------------------
# Each entry: matcher(ename, evalue) -> bool, and a builder(ctx) -> dict.

def _missing_name(evalue: str) -> Optional[str]:
    m = re.search(r"name '([^']+)' is not defined", evalue) or \
        re.search(r"'([^']+)' is not defined", evalue)
    return m.group(1) if m else None


def _missing_module(evalue: str) -> Optional[str]:
    m = re.search(r"No module named '([^']+)'", evalue)
    return m.group(1) if m else None


def _missing_key(evalue: str) -> Optional[str]:
    m = re.search(r"\'([^']+)\'", evalue)
    return m.group(1) if m else None


PY_RULES = {
    "NameError": lambda ctx: {
        "title": "A name is used before it exists",
        "cause": (
            f"The variable or function `{_missing_name(ctx['evalue']) or 'it'}` "
            "hasn't been defined yet in this runtime. Either it's misspelled, it "
            "lives in a cell you haven't run, or you reset the runtime and lost it."
        ),
        "fix": [
            "Check the spelling and capitalisation of the name.",
            "Run the earlier cell that defines it (Runtime ▸ Run all re-runs everything in order).",
            "If it comes from a library, make sure you `import` it first.",
        ],
        "snippet": _name_snippet(ctx),
    },
    "ModuleNotFoundError": lambda ctx: {
        "title": "A library isn't installed",
        "cause": (
            f"Python can't find the `{_missing_module(ctx['evalue']) or 'module'}` "
            "package in this environment."
        ),
        "fix": [
            f"Install it in a cell: `!pip install {(_missing_module(ctx['evalue']) or 'package').split('.')[0]}`",
            "Then re-run this cell.",
        ],
        "snippet": f"!pip install {(_missing_module(ctx['evalue']) or 'package').split('.')[0]}",
    },
    "ImportError": lambda ctx: {
        "title": "An import failed",
        "cause": "The module exists but the specific name you imported from it doesn't, "
                 "or a dependency is missing.",
        "fix": [
            "Double-check the imported symbol name against the library's docs.",
            "Confirm the library version matches what your code expects.",
        ],
        "snippet": None,
    },
    "TypeError": lambda ctx: {
        "title": "An operation got the wrong type",
        "cause": (
            "You combined or called values whose types don't fit — for example "
            "adding a string to a number, or calling something that isn't a function. "
            f"Details: {ctx['evalue']}"
        ),
        "fix": [
            "Convert types explicitly where needed: `str(x)`, `int(x)`, `float(x)`.",
            "Print the values just before the failing line to see their real types.",
        ],
        "snippet": None,
    },
    "ValueError": lambda ctx: {
        "title": "A value is the wrong shape or content",
        "cause": f"A function received a value of the right type but an unacceptable value. "
                 f"Details: {ctx['evalue']}",
        "fix": [
            "Inspect the offending value with a `print(...)` right before this line.",
            "Validate ranges/formats before passing values in.",
        ],
        "snippet": None,
    },
    "KeyError": lambda ctx: {
        "title": "A dictionary / DataFrame key is missing",
        "cause": (
            f"The key {ctx['evalue']} doesn't exist. For a DataFrame this usually means "
            "a column name is misspelled or has different casing/whitespace."
        ),
        "fix": [
            "List the available keys/columns: `print(df.columns.tolist())`.",
            "Match the exact name, including capitalisation and spaces.",
            "Use `.get(key, default)` for dicts when a key may be absent.",
        ],
        "snippet": "print(df.columns.tolist())",
    },
    "IndexError": lambda ctx: {
        "title": "An index is out of range",
        "cause": f"You asked for a position that doesn't exist in the list/array. "
                 f"Details: {ctx['evalue']}",
        "fix": [
            "Check the length first: `print(len(seq))`.",
            "Remember indices start at 0 and the last item is `len(seq) - 1`.",
        ],
        "snippet": None,
    },
    "ZeroDivisionError": lambda ctx: {
        "title": "Division by zero",
        "cause": "The denominator evaluated to 0.",
        "fix": [
            "Guard the division: `value = a / b if b != 0 else 0`.",
            "Trace where the denominator becomes zero.",
        ],
        "snippet": "value = a / b if b != 0 else 0",
    },
    "FileNotFoundError": lambda ctx: {
        "title": "The file path doesn't exist",
        "cause": "The file you're trying to open isn't where the code is looking. In this "
                 "notebook the working directory is your Files sidebar folder.",
        "fix": [
            "Upload the file via the Files panel on the left.",
            "Reference it by its plain name, e.g. `pd.read_csv('data.csv')`.",
            "List what's available: `import os; print(os.listdir())`.",
        ],
        "snippet": "import os; print(os.listdir())",
    },
    "AttributeError": lambda ctx: {
        "title": "That attribute/method doesn't exist",
        "cause": f"The object doesn't have the attribute or method you used. "
                 f"Details: {ctx['evalue']}",
        "fix": [
            "Check the spelling of the method.",
            "Confirm the object is the type you think it is (`print(type(obj))`).",
        ],
        "snippet": "print(type(obj), dir(obj))",
    },
    "SyntaxError": lambda ctx: {
        "title": "The code isn't valid Python syntax",
        "cause": f"Python couldn't parse the cell. Details: {ctx['evalue']}",
        "fix": [
            "Look for a missing `:` after if/for/while/def, an unclosed bracket, or a stray comma.",
            "Check indentation is consistent (spaces, not mixed with tabs).",
        ],
        "snippet": None,
    },
    "IndentationError": lambda ctx: {
        "title": "The indentation is off",
        "cause": "A block's lines aren't aligned consistently.",
        "fix": [
            "Use 4 spaces per level and keep all lines in a block at the same depth.",
            "Make sure the line after a `:` is indented.",
        ],
        "snippet": None,
    },
}

# AIDL kinds reuse the Python explanations where the meaning matches, with a
# couple of DSL-specific notes.
AIDL_RULES = {
    "SyntaxError": lambda ctx: {
        "title": "AIDL syntax problem",
        "cause": f"The AIDL parser couldn't read this line. Details: {ctx['evalue']}",
        "fix": [
            "Blocks need a `:` and an indented body, e.g. `if x > 3:` then an indented line.",
            "Strings use quotes; statements are one per line.",
            "Open the Syntax Manual (book icon) for the full grammar.",
        ],
        "snippet": None,
    },
    "NameError": lambda ctx: {
        "title": "Unknown variable or function in AIDL",
        "cause": f"`{_missing_name(ctx['evalue']) or 'that name'}` isn't defined. AIDL "
                 "variables persist across cells once you run the cell that creates them.",
        "fix": [
            "Run the earlier AIDL cell that assigns it.",
            "ML helpers are `load(...)`, `classifier(...)`, `regressor(...)`.",
            "Check spelling.",
        ],
        "snippet": None,
    },
    "ValueError": lambda ctx: {
        "title": "AIDL value problem",
        "cause": ctx["evalue"],
        "fix": [
            "If it's a missing file, upload it in the Files sidebar and use its name in `load(\"...\")`.",
            "If it's an index, remember lists start at 0.",
        ],
        "snippet": None,
    },
    "TypeError": lambda ctx: {
        "title": "AIDL type problem",
        "cause": ctx["evalue"],
        "fix": [
            "Use `str(x)` to join text with numbers in `print`.",
            "`train` and `predict` operate on a dataset from `load(...)`.",
        ],
        "snippet": None,
    },
    "RuntimeError": lambda ctx: {
        "title": "AIDL runtime problem",
        "cause": ctx["evalue"],
        "fix": [
            "Train a model before calling `predict`: `model.train(data)`.",
            "Avoid infinite loops — check your `while` conditions.",
        ],
        "snippet": None,
    },
}


def _name_snippet(ctx) -> Optional[str]:
    name = _missing_name(ctx["evalue"])
    if not name:
        return None
    return f"{name} = ...   # define {name} before using it"


def explain_error(language: str, code: str, error: Dict) -> Dict:
    """Return a structured, deterministic explanation for an error."""
    ename = (error or {}).get("ename", "Error")
    evalue = (error or {}).get("evalue", "")
    line = (error or {}).get("line")
    ctx = {"ename": ename, "evalue": evalue, "line": line, "code": code}

    rules = AIDL_RULES if language == "aidl" else PY_RULES
    builder = rules.get(ename) or PY_RULES.get(ename)
    if builder is None:
        explanation = {
            "title": f"{ename}",
            "cause": evalue or "An error occurred while running this cell.",
            "fix": [
                "Read the message above carefully — it usually names the exact problem.",
                "Print the values involved just before the failing line.",
            ],
            "snippet": None,
        }
    else:
        explanation = builder(ctx)

    line_hint = f" on line {line}" if line else ""
    explanation["headline"] = f"{explanation['title']}{line_hint}."
    explanation["ename"] = ename
    explanation["line"] = line
    explanation["mode"] = "deterministic"
    return explanation


def explanation_to_markdown(exp: Dict) -> str:
    lines = [f"### {exp.get('headline', exp.get('title', 'Error'))}", "", exp.get("cause", ""), ""]
    fixes = exp.get("fix") or []
    if fixes:
        lines.append("**How to fix it**")
        for f in fixes:
            lines.append(f"- {f}")
        lines.append("")
    if exp.get("snippet"):
        lines.append("**Try this**")
        lines.append("```")
        lines.append(exp["snippet"])
        lines.append("```")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
#  Optional LLM layer (OpenAI / Gemini via REST)
# --------------------------------------------------------------------------
def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _llm_openai(prompt: str, api_key: str, model: str) -> str:
    body = {
        "model": model or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a concise, friendly coding tutor inside a "
                                          "Colab-like notebook. Explain errors and answer questions "
                                          "about Python and the AIDL DSL. Be practical and short."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    out = _http_post_json(
        "https://api.openai.com/v1/chat/completions",
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    return out["choices"][0]["message"]["content"]


def _llm_gemini(prompt: str, api_key: str, model: str) -> str:
    model = model or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    out = _http_post_json(url, body, {"Content-Type": "application/json"})
    return out["candidates"][0]["content"]["parts"][0]["text"]


def llm_reply(prompt: str, provider: str, api_key: str, model: str = "") -> str:
    provider = (provider or "").lower()
    if provider == "openai":
        return _llm_openai(prompt, api_key, model)
    if provider in ("gemini", "google"):
        return _llm_gemini(prompt, api_key, model)
    raise ValueError("unsupported provider")


def assistant_chat(
    message: str,
    context: Dict,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: str = "",
) -> Dict:
    """Answer a user question in the assistant panel.

    Uses the LLM when a provider+key are available; otherwise returns a helpful
    deterministic response built from the current cell context.
    """
    provider = provider or os.getenv("AGENT_LLM_PROVIDER")
    api_key = api_key or (
        os.getenv("OPENAI_API_KEY") if provider == "openai"
        else os.getenv("GOOGLE_API_KEY") if provider in ("gemini", "google")
        else None
    )

    if provider and api_key:
        prompt = _build_prompt(message, context)
        try:
            text = llm_reply(prompt, provider, api_key, model)
            return {"text": text, "mode": f"llm:{provider}"}
        except Exception as exc:  # graceful fallback
            fallback = _deterministic_chat(message, context)
            fallback["text"] += (
                f"\n\n_(LLM call failed: {exc}. Showing the built-in explanation instead.)_"
            )
            return fallback

    return _deterministic_chat(message, context)


def _build_prompt(message: str, context: Dict) -> str:
    parts = [f"User question: {message}", ""]
    if context.get("language"):
        parts.append(f"Cell language: {context['language']}")
    if context.get("code"):
        parts.append("Cell code:\n```\n" + context["code"][:4000] + "\n```")
    if context.get("error"):
        e = context["error"]
        parts.append(f"Error: {e.get('ename')}: {e.get('evalue')} (line {e.get('line')})")
    return "\n".join(parts)


def _deterministic_chat(message: str, context: Dict) -> Dict:
    error = context.get("error")
    language = context.get("language", "python")
    if error:
        exp = explain_error(language, context.get("code", ""), error)
        text = explanation_to_markdown(exp)
        text += "\n\n_Built-in assistant — add an API key in the panel for free-form answers._"
        return {"text": text, "mode": "deterministic"}

    # No active error: give general guidance keyed off the question.
    msg = message.lower()
    if any(w in msg for w in ("dataset", "csv", "upload", "file", "load")):
        text = (
            "To use a dataset: open the **Files** panel on the left, upload your `.csv`, "
            "then read it by name.\n\n"
            "- Python: `import pandas as pd; df = pd.read_csv('your.csv')`\n"
            "- AIDL: `data = load(\"your.csv\")`"
        )
    elif any(w in msg for w in ("aidl", "dsl", "syntax", "grammar")):
        text = (
            "AIDL v2 is Python-like with ML built-ins. Quick tour:\n\n"
            "```\ndata = load(\"iris.csv\")\nmodel = classifier(target=\"species\")\n"
            "model.train(data, epochs=10)\nprint(\"accuracy\", model.accuracy)\n```\n\n"
            "Open the **Syntax Manual** (book icon in the toolbar) for the full guide."
        )
    elif any(w in msg for w in ("plot", "chart", "graph", "matplotlib", "visual")):
        text = (
            "Plots render inline automatically. Example:\n\n"
            "```python\nimport matplotlib.pyplot as plt\nplt.plot([1,2,3],[1,4,9])\n"
            "plt.title('demo')\n```"
        )
    else:
        text = (
            "I'm the built-in assistant. I automatically explain any cell error, and I can "
            "help with datasets, plotting, and AIDL syntax. For open-ended questions, add an "
            "OpenAI or Gemini API key in this panel to unlock the full agentic mode."
        )
    return {"text": text, "mode": "deterministic"}
