"""Azure AI Search tool wrappers for agent use.

These plain Python functions are passed as `tools` to Agent definitions.
The agent framework serializes them automatically and the model can call
them at runtime to retrieve grounded context.

Two tools mirror our existing service layer:
  search_excel_ratings  — Excel broadcast data (tv-promos index)
  search_word_strategy  — Word strategy / marketing docs (word-docs index)
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def search_excel_ratings(query: str) -> str:
    """Search TV show broadcast ratings, averages, peaks, and numeric data.

    Use this tool for questions about ratings, viewership numbers, season
    performance, rankings, or any quantitative TV show metric.

    Args:
        query: The search query in Hebrew or English.

    Returns:
        Formatted retrieval results from the Excel ratings index.
    """
    from app.search_word_docs import search_excel_promos

    log.info("Tool: search_excel_ratings  query=%r", query[:80])
    hits = search_excel_promos(query, top=5)
    if not hits:
        return "לא נמצאו נתונים במאגר ה-Excel עבור שאילתה זו."

    lines: list[str] = ["[Excel ratings data]"]
    for i, h in enumerate(hits, 1):
        parts = [f"[{i}]"]
        for key in ("show_name", "season", "date", "rating", "source_file"):
            val = h.get(key, "")
            if val:
                parts.append(f"{key}: {val}")
        lines.append("  " + " | ".join(parts))
    return "\n".join(lines)


def search_word_strategy(query: str) -> str:
    """Search strategy briefs, campaign slogans, and marketing documents.

    Use this tool for questions about strategy, phrasing, slogans, quotes,
    briefs, or any qualitative marketing or editorial content.

    Args:
        query: The search query in Hebrew or English.

    Returns:
        Formatted retrieval results from the Word documents index.
    """
    from app.search_word_docs import search_word_docs

    log.info("Tool: search_word_strategy  query=%r", query[:80])
    hits = search_word_docs(query, top=5)
    if not hits:
        return "לא נמצאו מסמכים במאגר ה-Word עבור שאילתה זו."

    lines: list[str] = ["[Word strategy documents]"]
    for i, h in enumerate(hits, 1):
        chunk_id  = h.get("chunk_id", "")
        src_file  = h.get("source_file", "")
        caption   = h.get("caption", "")
        content   = h.get("content", "")[:900]
        score     = h.get("reranker_score", 0.0)

        lines.append(f"  [{i}] {src_file}  chunk={chunk_id}  score={score:.2f}")
        if caption:
            lines.append(f"       caption: {caption}")
        if content:
            lines.append(f"       {content}")
    return "\n".join(lines)
