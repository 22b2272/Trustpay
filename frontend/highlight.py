"""Render the user's own instruction with each clause marked: green if every check tied to it passed,
red if any check tied to it failed. Pure function so it can be unit tested without Streamlit."""
import html

GREEN, RED = "#1a7f37", "#cf222e"


def highlight_instruction(text: str, receipt: list[dict]) -> str:
    status: dict[str, dict] = {}
    for row in receipt:
        phrase = row.get("from_your_words", "")
        if not phrase or phrase not in text:
            continue
        s = status.setdefault(phrase, {"failed": [], "ok": True})
        if not row["passed"]:
            s["ok"] = False
            s["failed"].append(row["check"])
    spans = sorted((text.index(p), text.index(p) + len(p), p) for p in status)
    out, pos = [], 0
    for start, end, phrase in spans:
        if start < pos:  # overlapping phrase: skip rather than render broken markup
            continue
        out.append(html.escape(text[pos:start]))
        s = status[phrase]
        color = GREEN if s["ok"] else RED
        tip = "all checks passed" if s["ok"] else "violated: " + ", ".join(s["failed"])
        out.append(f'<mark style="background:{color}22;color:{color};border-bottom:2px solid {color};'
                   f'padding:0 3px;border-radius:3px" title="{html.escape(tip)}">{html.escape(phrase)}</mark>')
        pos = end
    out.append(html.escape(text[pos:]))
    return "".join(out)
