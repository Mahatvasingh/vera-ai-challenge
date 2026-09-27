import re
from typing import List, Any
 
 
def extract_quant_tokens(text: str) -> List[str]:
    """Finds currency amounts, percentages, numbers, and ratings."""
    pattern = r'(?:₹\s*\d+(?:,\d+)*(?:\.\d+)?|\b\d+(?:,\d+)*(?:\.\d+)?%|\b\d+(?:,\d+)*(?:\.\d+)?★?)'
    return re.findall(pattern, text)
 
 
def normalize_context_string(contexts: List[Any]) -> str:
    parts = []
    for item in contexts:
        if isinstance(item, dict):
            parts.append(normalize_context_string(list(item.values())))
        elif isinstance(item, list):
            parts.append(normalize_context_string(item))
        elif item is not None:
            parts.append(str(item))
    return " ".join(parts).lower()
 
 
def passes_grounding(composed_body: str, contexts: List[Any]) -> bool:
    """Ensures every number, price, or percentage in the message exists in the input data."""
    tokens = extract_quant_tokens(composed_body)
    context_corpus = normalize_context_string(contexts)
 
    for token in tokens:
        clean = token.replace("₹", "").replace("%", "").replace("★", "").replace(",", "").strip().lower()
        if clean in {"1", "2", "3", "24", "48"}:
            continue
        if clean not in context_corpus:
            return False
    return True
 
 
def check_taboos(composed_body: str, taboos: List[str]) -> bool:
    """Verifies that no vertical forbidden words (e.g., '100% cure') appear in the text."""
    body_lower = composed_body.lower()
    return not any(taboo.lower() in body_lower for taboo in taboos if taboo)
 
 
def normalize_for_repeat_check(text: str) -> str:
    """Collapse whitespace/case/punctuation so near-identical auto-replies match."""
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', text or '')).strip().lower()
 
 
def is_verbatim_repeat(candidate: str, history: List[str], min_hits: int = 3) -> bool:
    """
    True if `candidate` matches an earlier message in `history` at least
    (min_hits - 1) times before (i.e. this occurrence would be the min_hits'th).
    Matches the brief's stated heuristic: "same message verbatim 3+ times = auto-reply".
    """
    norm_candidate = normalize_for_repeat_check(candidate)
    if not norm_candidate:
        return False
    hits = sum(1 for h in history if normalize_for_repeat_check(h) == norm_candidate)
    return (hits + 1) >= min_hits