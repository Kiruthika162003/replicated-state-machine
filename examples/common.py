"""Formatting shared by the example scripts, so each one is about its subject."""

from __future__ import annotations

from collections.abc import Sequence

WIDTH = 78


def rule(title: str = "") -> str:
    """A horizontal rule, with a title in it when there is one."""
    if not title:
        return "-" * WIDTH
    return f"-- {title} " + "-" * max(0, WIDTH - len(title) - 4)


def table(rows: Sequence[dict], columns: Sequence[str] | None = None) -> str:
    """A list of mappings as aligned columns.

    The column order comes from the first row rather than from sorting, because the order a
    measurement returns its fields in is usually the order it wants them read in.
    """
    rows = list(rows)
    if not rows:
        return "nothing to show"
    names = list(columns or rows[0])
    widths = {
        name: max(len(str(name)), *(len(str(one.get(name, ""))) for one in rows))
        for name in names
    }
    out = ["  ".join(str(name).ljust(widths[name]) for name in names)]
    out.append("  ".join("-" * widths[name] for name in names))
    out += [
        "  ".join(str(one.get(name, "")).ljust(widths[name]) for name in names) for one in rows
    ]
    return "\n".join(out)


def pairs(mapping: dict, indent: str = "") -> str:
    """A mapping as one aligned line per key."""
    if not mapping:
        return f"{indent}nothing to show"
    width = max(len(str(one)) for one in mapping)
    return "\n".join(
        f"{indent}{str(name).ljust(width)}  {_show(value)}" for name, value in mapping.items()
    )


def _show(value: object) -> str:
    """One value, with the booleans spelled out rather than printed as True and False."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def bar(share: float, width: int = 40) -> str:
    """A share of one as a bar, for a column that is easier to scan than to read."""
    filled = max(0, min(width, round(share * width)))
    return "#" * filled + "." * (width - filled)
