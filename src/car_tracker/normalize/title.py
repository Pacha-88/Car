"""A readable name for a listing, always.

Marketplace cards are only as good as what the seller typed, and the field
this project reads as a title is optional on every source: AutoScout24's
`modelVersionInput` is blank when nobody filled in a trim description, and
Tesla's own inventory has no free-text headline at all. Left alone, those
listings rendered as "Untitled" in the dashboard next to neighbours showing
real ad titles.

Nothing here invents detail. When a source gives no words of its own, the
fallback says only what is certainly true - which model it is - because
that is exactly what the marketplaces themselves show for those ads.
"""

from __future__ import annotations

MODEL_NAMES = {"model_3": "Model 3", "model_y": "Model Y"}


def model_display_name(model: str) -> str:
    """"model_y" -> "Model Y". Falls through unknown keys unchanged."""
    return MODEL_NAMES.get(model, model)


def ensure_title(title: str | None, *, model: str) -> str:
    """`title` if it says anything, else the model's own name."""
    cleaned = (title or "").strip()
    return cleaned or f"Tesla {model_display_name(model)}"
