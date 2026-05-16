import json
import math
import re
from pathlib import Path
from statistics import median
from typing import Iterable, List, Sequence, Tuple


ALLOWED_TEXT_CHARS = re.compile(
    r"[0-9A-Za-z\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3\u3040-\u30FF\u4E00-\u9FFF\s"
    r"\.,;:!?\-_/\\%&\(\)\[\]\{\}\+\*\#'\"“”‘’·~`=@|<>$^]"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TICKER_RE = re.compile(r"\(([0-9]{4,6})\)")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path: Path, payload) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_bbox(bbox: Sequence[float], width: float, height: float) -> List[float]:
    x1, y1, x2, y2 = bbox
    if not width or not height:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(max(0.0, min(1.0, x1 / width)), 6),
        round(max(0.0, min(1.0, y1 / height)), 6),
        round(max(0.0, min(1.0, x2 / width)), 6),
        round(max(0.0, min(1.0, y2 / height)), 6),
    ]


def bbox_area(bbox: Sequence[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_iou(left: Sequence[float], right: Sequence[float]) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1 = max(lx1, rx1)
    iy1 = max(ly1, ry1)
    ix2 = min(lx2, rx2)
    iy2 = min(ly2, ry2)
    inter = bbox_area([ix1, iy1, ix2, iy2])
    if inter <= 0:
        return 0.0
    union = bbox_area(left) + bbox_area(right) - inter
    if union <= 0:
        return 0.0
    return inter / union


def union_bbox(boxes: Iterable[Sequence[float]]) -> List[int]:
    boxes = list(boxes)
    if not boxes:
        return [0, 0, 0, 0]
    xs1 = [box[0] for box in boxes]
    ys1 = [box[1] for box in boxes]
    xs2 = [box[2] for box in boxes]
    ys2 = [box[3] for box in boxes]
    return [int(min(xs1)), int(min(ys1)), int(max(xs2)), int(max(ys2))]


def median_or_default(values: Sequence[float], default: float) -> float:
    values = [value for value in values if value is not None]
    return float(median(values)) if values else default


def count_columns(x_positions: Sequence[float], page_width: float) -> int:
    if not x_positions or page_width <= 0:
        return 1
    sorted_positions = sorted(x_positions)
    clusters = 1
    previous = sorted_positions[0]
    threshold = page_width * 0.18
    for value in sorted_positions[1:]:
        if value - previous > threshold:
            clusters += 1
        previous = value
    return max(1, min(clusters, 4))


def clean_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def script_buckets(text: str) -> Tuple[int, int, int, int]:
    hangul = latin = cjk = other = 0
    for char in text:
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            hangul += 1
        elif ("A" <= char <= "Z") or ("a" <= char <= "z") or ("0" <= char <= "9"):
            latin += 1
        elif 0x3040 <= code <= 0x30FF or 0x4E00 <= code <= 0x9FFF:
            cjk += 1
        elif not char.isspace():
            other += 1
    return hangul, latin, cjk, other


def weird_char_ratio(text: str) -> float:
    if not text:
        return 1.0
    meaningful = [char for char in text if not char.isspace()]
    if not meaningful:
        return 1.0
    weird = sum(1 for char in meaningful if not ALLOWED_TEXT_CHARS.fullmatch(char))
    return weird / len(meaningful)


def long_token_ratio(text: str) -> float:
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return 1.0
    long_tokens = [token for token in tokens if len(token) >= 24]
    return len(long_tokens) / len(tokens)


def repeated_chunk_penalty(text: str) -> float:
    if not text:
        return 1.0
    longest = 0
    current = 0
    previous = ""
    for char in text:
        if char == previous and not char.isspace():
            current += 1
        else:
            current = 1
        previous = char
        longest = max(longest, current)
    token_counts = {}
    for token in re.findall(r"\S+", text):
        token_counts[token] = token_counts.get(token, 0) + 1
    repeated_tokens = sum(count for count in token_counts.values() if count >= 4)
    return min(1.0, max(longest / 12.0, repeated_tokens / max(1, len(token_counts))))


def text_quality_score(text: str) -> float:
    cleaned = clean_text(text)
    if not cleaned:
        return 0.0
    weird = weird_char_ratio(cleaned)
    hangul, latin, cjk, other = script_buckets(cleaned)
    script_groups = sum(1 for count in (hangul, latin, cjk, other) if count > 0)
    mixed_penalty = 0.0
    if script_groups >= 4:
        mixed_penalty = 1.0
    elif script_groups == 3 and other > 0:
        mixed_penalty = 0.7
    elif other > 0:
        mixed_penalty = min(1.0, other / max(1, len(cleaned)))
    repeat_penalty = max(repeated_chunk_penalty(cleaned), long_token_ratio(cleaned))
    blank_penalty = 0.0
    if len(cleaned) < 6:
        blank_penalty = 1.0
    elif len(cleaned) < 15:
        blank_penalty = 0.5
    score = 1.0
    score -= weird * 0.4
    score -= mixed_penalty * 0.3
    score -= repeat_penalty * 0.2
    score -= blank_penalty * 0.1
    return max(0.0, min(1.0, round(score, 4)))


def detect_language(texts: Sequence[str]) -> str:
    joined = " ".join(texts)
    hangul, latin, cjk, _ = script_buckets(joined)
    if hangul >= max(latin, cjk):
        return "ko"
    if latin >= cjk:
        return "en"
    return "unknown"


def has_financial_signal(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    keywords = [
        "buy",
        "sell",
        "hold",
        "목표주가",
        "현재주가",
        "상승여력",
        "consensus data",
        "key data",
        "stock price",
        "financial data",
    ]
    return any(keyword in lowered for keyword in keywords) or bool(TICKER_RE.search(text))


def infer_alignment(bbox_norm: Sequence[float]) -> str:
    x1, _, x2, _ = bbox_norm
    center = (x1 + x2) / 2.0
    if center < 0.4:
        return "left"
    if center > 0.6:
        return "right"
    return "center"


def stable_hash(parts: Sequence[str]) -> str:
    import hashlib

    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


def relative_gap(upper_bbox: Sequence[float], lower_bbox: Sequence[float], page_height: float) -> float:
    if page_height <= 0:
        return 0.0
    return max(0.0, lower_bbox[1] - upper_bbox[3]) / page_height


def area_ratio(bbox: Sequence[float], width: float, height: float) -> float:
    page_area = max(1.0, width * height)
    return bbox_area(bbox) / page_area


def pick_best_path(paths: Sequence[Path]) -> Path:
    for path in paths:
        if path and path.exists():
            return path
    return paths[0]
