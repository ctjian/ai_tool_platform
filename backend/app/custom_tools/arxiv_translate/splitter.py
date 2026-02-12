"""Chunking helpers for LaTeX translation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List
import re


@dataclass
class LatexSegment:
    text: str
    translatable: bool
    start_line: int
    end_line: int


SHORT_SEGMENT_MIN_CHARS = 42


try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None


@lru_cache(maxsize=1)
def _get_encoder():
    if tiktoken is None:
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - tokenizer unavailable
        return None


def estimate_token_count(text: str) -> int:
    enc = _get_encoder()
    if enc is None:
        return max(1, len(text) // 4)
    try:
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        return max(1, len(text) // 4)


def strip_latex_comments(text: str) -> str:
    """
    Remove LaTeX comments before segmentation (aligned with GPT-Academic rm_comments):
    - drop full-line comments
    - remove inline comments that start with unescaped %
    """
    lines: List[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        lines.append(line)
    no_full_line = "\n".join(lines)
    return re.sub(r"(?m)(?<!\\)%.*$", "", no_full_line)


def _mark_range(mask: List[bool], start: int, end: int, value: bool) -> None:
    s = max(0, int(start))
    e = min(len(mask), int(end))
    if s >= e:
        return
    mask[s:e] = [value] * (e - s)


def _mark_pattern(
    text: str,
    mask: List[bool],
    pattern: str,
    *,
    flags: int = 0,
    value: bool = False,
    max_lines: int | None = None,
) -> None:
    for m in re.finditer(pattern, text, flags):
        if max_lines is not None and m.group(0).count("\n") >= max_lines:
            continue
        _mark_range(mask, m.start(), m.end(), value)


def _unmask_group(
    text: str,
    mask: List[bool],
    pattern: str,
    *,
    flags: int = 0,
    group: int = 1,
) -> None:
    for m in re.finditer(pattern, text, flags):
        if group > (m.lastindex or 0):
            continue
        start, end = m.span(group)
        _mark_range(mask, start, end, True)


def _unmask_group_careful_brace(
    text: str,
    mask: List[bool],
    pattern: str,
    *,
    flags: int = 0,
    group: int = 1,
) -> None:
    """
    Similar to GPT-Academic reverse_forbidden_text_careful_brace:
    unmask the content group and keep wrapper preserved.
    """
    compiled = re.compile(pattern, flags)
    for m in compiled.finditer(text):
        if group > (m.lastindex or 0):
            continue
        begin = m.regs[group][0]
        p = begin
        brace_level = 0
        for _ in range(1024 * 16):
            if p >= len(text):
                break
            c = text[p]
            if c == "}" and brace_level == 0:
                break
            if c == "{":
                brace_level += 1
            elif c == "}":
                brace_level -= 1
            p += 1
        end = p
        _mark_range(mask, begin, end, True)


def _mark_frontmatter_region(text: str, mask: List[bool]) -> None:
    """
    Preserve title metadata area between document start and maketitle.
    """
    begin_doc = re.search(r"\\begin\{document\}", text)
    make_title = re.search(r"\\maketitle\b", text)
    if not begin_doc or not make_title:
        return
    if make_title.start() <= begin_doc.end():
        return
    # Guard against unusual templates with distant \maketitle.
    if (make_title.start() - begin_doc.end()) > 12000:
        return
    _mark_range(mask, begin_doc.end(), make_title.end(), False)


def _mark_command_blocks(text: str, mask: List[bool], commands: List[str]) -> None:
    """
    Preserve whole command blocks for metadata commands with brace payload.
    Supports optional stars and bracket options, e.g. \\author[1]{...}.
    """
    if not commands:
        return
    cmd_alt = "|".join(re.escape(cmd) for cmd in commands)
    pattern = re.compile(rf"\\(?:{cmd_alt})\*?(?:\s*\[[^\]]*\])*\s*\{{", re.DOTALL)
    for m in pattern.finditer(text):
        matched = m.group(0)
        brace_offset = matched.rfind("{")
        if brace_offset < 0:
            continue
        begin = m.start()
        p = m.start() + brace_offset
        brace_level = 0
        for _ in range(1024 * 32):
            if p >= len(text):
                break
            c = text[p]
            if c == "{":
                brace_level += 1
            elif c == "}":
                brace_level -= 1
                if brace_level == 0:
                    p += 1
                    break
            p += 1
        _mark_range(mask, begin, p, False)


def _build_translation_mask(text: str) -> List[bool]:
    mask = [True] * len(text)

    # Preserve preamble and title metadata region by default.
    preamble_end = re.search(r"\\maketitle|\\begin\{document\}", text)
    if preamble_end:
        _mark_range(mask, 0, preamble_end.end(), False)
    _mark_frontmatter_region(text, mask)

    _mark_command_blocks(
        text,
        mask,
        [
            "title",
            "author",
            "date",
            "thanks",
            "institute",
            "affiliation",
            "affil",
            "address",
            "email",
            "emails",
            "icmltitle",
            "icmlauthor",
            "icmlaffiliation",
            "icmlcorrespondingauthor",
            "authornote",
        ],
    )

    _mark_short_begin_end_blocks(text, mask, limit_n_lines=42)

    preserve_rules = [
        (r"\\iffalse(.*?)\\fi", re.DOTALL, None),
        (r"\$\$([^$]+)\$\$", re.DOTALL, None),
        (r"\\\[.*?\\\]", re.DOTALL, None),
        (r"\\section\*?\{.*?\}", 0, None),
        (r"\\subsection\*?\{.*?\}", 0, None),
        (r"\\subsubsection\*?\{.*?\}", 0, None),
        (r"\\bibliography\{.*?\}", 0, None),
        (r"\\bibliographystyle\{.*?\}", 0, None),
        (r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.DOTALL, None),
        (r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", re.DOTALL, None),
        (r"\\begin\{algorithm\}.*?\\end\{algorithm\}", re.DOTALL, None),
        (r"\\begin\{wraptable\}.*?\\end\{wraptable\}", re.DOTALL, None),
        (r"\\begin\{wrapfigure\*?\}.*?\\end\{wrapfigure\*?\}", re.DOTALL, None),
        (r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", re.DOTALL, None),
        (r"\\begin\{table\*?\}.*?\\end\{table\*?\}", re.DOTALL, None),
        (r"\\begin\{minipage\*?\}.*?\\end\{minipage\*?\}", re.DOTALL, None),
        (r"\\begin\{multline\*?\}.*?\\end\{multline\*?\}", re.DOTALL, None),
        (r"\\begin\{align\*?\}.*?\\end\{align\*?\}", re.DOTALL, None),
        (r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", re.DOTALL, None),
        (r"\\includepdf\[[^\]]*\]\{[^}]*\}", 0, None),
        (r"\\(clearpage|newpage|appendix|tableofcontents)\b", 0, None),
        (r"\\include\{[^}]*\}", 0, None),
        (r"\\vspace\{.*?\}", 0, None),
        (r"\\hspace\{.*?\}", 0, None),
        (r"\\label\{.*?\}", 0, None),
        (r"\\begin\{[^}]*\}", 0, None),
        (r"\\end\{[^}]*\}", 0, None),
        (r"\\item(?:\[[^\]]*\])?\s*", 0, None),
        (r"\\pdfinfo\s*\{.*?\}", re.DOTALL, None),
    ]

    for pattern, flags, max_lines in preserve_rules:
        _mark_pattern(text, mask, pattern, flags=flags, value=False, max_lines=max_lines)

    # Re-enable abstract/caption bodies for translation.
    _unmask_group(
        text,
        mask,
        r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
        flags=re.DOTALL,
        group=1,
    )
    _unmask_group_careful_brace(text, mask, r"\\abstract\{(.*?)\}", flags=re.DOTALL, group=1)
    _unmask_group_careful_brace(text, mask, r"\\caption\{(.*?)\}", flags=re.DOTALL, group=1)
    return mask


def _mark_short_begin_end_blocks(text: str, mask: List[bool], *, limit_n_lines: int = 42) -> None:
    """
    Port of GPT-Academic set_forbidden_text_begin_end:
    recursively preserve short begin/end environments, but keep selected
    text-heavy environments expandable so inner structures can be handled.
    """
    pattern = re.compile(r"\\begin\{([a-zA-Z\*]+)\}(.*?)\\end\{\1\}", re.DOTALL)
    white_list = {
        "document",
        "abstract",
        "theorem",
        "proposition",
        "corollary",
        "lemma",
        "definition",
        "proof",
        "remark",
        "claim",
        "example",
        "restatable",
        "sproof",
        "em",
        "emph",
        "textit",
        "textbf",
        "itemize",
        "enumerate",
    }

    def _walk(sub_text: str, abs_offset: int) -> None:
        for m in pattern.finditer(sub_text):
            cmd = m.group(1)
            body = m.group(2)
            whole_start, whole_end = m.span(0)
            body_start, _ = m.span(2)
            if cmd in white_list or body.count("\n") >= limit_n_lines:
                _walk(body, abs_offset + body_start)
            else:
                _mark_range(mask, abs_offset + whole_start, abs_offset + whole_end, False)

    _walk(text, 0)


def _post_process_chunks(chunks: List[tuple[str, bool]]) -> List[tuple[str, bool]]:
    """
    Lightweight post-process aligned with GPT-Academic:
    1) very short transform chunks are preserved
    2) adjacent chunks with same flag are merged
    """
    adjusted: List[tuple[str, bool]] = []
    for text, translatable in chunks:
        flag = bool(translatable)
        if flag:
            core = text.strip("\n").strip()
            if len(core) < SHORT_SEGMENT_MIN_CHARS:
                flag = False
        adjusted.append((text, flag))

    merged: List[tuple[str, bool]] = []
    for text, flag in adjusted:
        if not merged:
            merged.append((text, flag))
            continue
        prev_text, prev_flag = merged[-1]
        if prev_flag == flag:
            merged[-1] = (prev_text + text, flag)
        else:
            merged.append((text, flag))
    return merged


def segment_latex_text(text: str) -> List[LatexSegment]:
    if not text:
        return []
    mask = _build_translation_mask(text)
    raw_chunks: List[tuple[str, bool]] = []

    i = 0
    n = len(text)
    while i < n:
        flag = mask[i]
        j = i + 1
        while j < n and mask[j] == flag:
            j += 1
        raw_chunks.append((text[i:j], bool(flag)))
        i = j

    chunks = _post_process_chunks(raw_chunks)
    segments: List[LatexSegment] = []
    current_line = 1
    for seg_text, flag in chunks:
        start_line = current_line
        line_inc = seg_text.count("\n")
        end_line = current_line + line_inc
        segments.append(
            LatexSegment(
                text=seg_text,
                translatable=flag,
                start_line=start_line,
                end_line=end_line,
            )
        )
        current_line = end_line
    return segments


def _pick_split_index(text: str, max_tokens: int) -> int:
    total_tokens = estimate_token_count(text)
    if total_tokens <= max_tokens or len(text) < 2:
        return -1

    target = int(len(text) * (max_tokens / max(total_tokens, 1)))
    target = min(max(1, target), len(text) - 1)
    min_pos = max(1, int(len(text) * 0.15))
    max_pos = min(len(text) - 1, int(len(text) * 0.85))
    candidates = []
    separators = ["\n\n", "\n", ". ", "。", "; ", "；", ", ", "，"]

    for sep in separators:
        left = text.rfind(sep, 0, target + 1)
        if left != -1:
            idx = left + len(sep)
            if min_pos <= idx <= max_pos:
                candidates.append(idx)

        right = text.find(sep, target)
        if right != -1:
            idx = right + len(sep)
            if min_pos <= idx <= max_pos:
                candidates.append(idx)

    if not candidates:
        return target
    return min(candidates, key=lambda x: abs(x - target))


def _split_text_to_token_limit(text: str, max_tokens: int) -> List[str]:
    if not text:
        return []
    if estimate_token_count(text) <= max_tokens:
        return [text]

    split_idx = _pick_split_index(text, max_tokens)
    if split_idx <= 0 or split_idx >= len(text):
        split_idx = len(text) // 2
    split_idx = min(max(1, split_idx), len(text) - 1)

    left = text[:split_idx]
    right = text[split_idx:]
    if not left or not right:
        return [text]

    return _split_text_to_token_limit(left, max_tokens) + _split_text_to_token_limit(right, max_tokens)


def split_translatable_segments_by_token_limit(
    segments: List[LatexSegment],
    *,
    max_tokens: int = 1024,
) -> List[LatexSegment]:
    out: List[LatexSegment] = []
    token_limit = max(256, int(max_tokens))

    for seg in segments:
        if (not seg.translatable) or estimate_token_count(seg.text) <= token_limit:
            out.append(seg)
            continue

        chunks = _split_text_to_token_limit(seg.text, token_limit)
        line_cursor = seg.start_line
        for chunk in chunks:
            line_inc = chunk.count("\n")
            out.append(
                LatexSegment(
                    text=chunk,
                    translatable=True,
                    start_line=line_cursor,
                    end_line=line_cursor + line_inc,
                )
            )
            line_cursor += line_inc
    return out


def build_translation_segments(text: str, *, max_tokens: int = 1024) -> List[LatexSegment]:
    base_segments = segment_latex_text(text)
    return split_translatable_segments_by_token_limit(base_segments, max_tokens=max_tokens)


def normalize_llm_translated_chunk(text: str) -> str:
    """
    Remove accidental markdown wrappers around translated tex chunks.
    """
    out = (text or "").strip()
    if out.startswith("```"):
        lines = out.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            out = "\n".join(lines[1:-1]).strip()
    return out


def _restore_edge_whitespace(original: str, translated: str) -> str:
    """
    Preserve leading/trailing whitespace from the original segment so
    translated content does not get glued to neighboring preserved chunks.
    """
    if not original:
        return translated
    lead_len = len(original) - len(original.lstrip())
    trail_len = len(original) - len(original.rstrip())
    lead = original[:lead_len] if lead_len > 0 else ""
    trail = original[len(original) - trail_len :] if trail_len > 0 else ""
    core = translated.strip()
    return f"{lead}{core}{trail}"


def _mod_in_bracket(match: re.Match[str]) -> str:
    cmd = match.group(1)
    payload = match.group(2)
    payload = payload.replace("：", ":").replace("，", ",")
    return "\\" + cmd + "{" + payload + "}"


def _brace_level(s: str) -> int:
    level = 0
    for ch in s:
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
    return level


def _join_most(translated: str, original: str) -> str:
    p_t = 0
    p_o = 0

    def _find_next(source: str, chars: list[str], begin: int):
        p = begin
        while p < len(source):
            if source[p] in chars:
                return p, source[p]
            p += 1
        return None, None

    while True:
        res_o, ch = _find_next(original, ["{", "}"], p_o)
        if res_o is None:
            break
        res_t, _ = _find_next(translated, [ch], p_t)
        if res_t is None:
            break
        p_o = res_o + 1
        p_t = res_t + 1
    return translated[:p_t] + original[p_o:]


def guard_translated_segment(original: str, translated: str) -> str:
    """
    Port of GPT-Academic's fix_content safeguards.
    """
    out = normalize_llm_translated_chunk(translated)
    if not out:
        return original

    # Typical model refusals / tool errors: hard fallback.
    banned_signals = [
        "Traceback",
        "[Local Message]",
        "抱歉，我无法",
        "公式无需翻译",
        "请提供您需要翻译的 LaTeX 片段",
        "请提供需要翻译的 LaTeX 片段",
        "Please provide the LaTeX",
        "I cannot comply",
        "I can’t comply",
        "I can't comply",
    ]
    if any(sig in out for sig in banned_signals):
        return original

    out = re.sub(r"(?<!\\)%", r"\\%", out)
    out = re.sub(r"\\([a-zA-Z]{2,20})\ \{", r"\\\1{", out)
    out = re.sub(r"\\\ ([a-zA-Z]{2,20})\{", r"\\\1{", out)
    out = re.sub(r"\\([a-zA-Z]{2,20})\{([^\}]*?)\}", _mod_in_bracket, out)

    # Keep command structure stable.
    if original.count("\\begin") != out.count("\\begin"):
        return original
    if original.count("\\end") != out.count("\\end"):
        return original
    if original.count("\\item") != out.count("\\item"):
        return original
    if original.count("\\caption") != out.count("\\caption"):
        return original

    # Escape underscore regression.
    if original.count(r"\_") > 0 and original.count(r"\_") > out.count(r"\_"):
        out = re.sub(r"(?<!\\)_", r"\\_", out)

    # Braces mismatch: align as much as possible, else fallback.
    if _brace_level(out) != _brace_level(original):
        out = _join_most(out, original)
        if _brace_level(out) != _brace_level(original):
            return original

    # Hard guard against extreme blow-up.
    if len(original) >= 200 and len(out) > len(original) * 3:
        return original

    return _restore_edge_whitespace(original, out)


def _find_matching_brace(text: str, open_pos: int) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return -1
    level = 0
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                return i
    return -1


def ensure_section_title_bold(text: str) -> str:
    """
    Force section titles to include \\textbf{...} as a fallback for templates
    that do not render section headers in bold.
    """
    if not text:
        return text

    cmd_re = re.compile(r"\\section\*?(?:\s*\[[^\]]*\])?\s*\{", re.DOTALL)
    out_parts: List[str] = []
    cursor = 0

    for m in cmd_re.finditer(text):
        open_pos = m.end() - 1  # points to "{"
        close_pos = _find_matching_brace(text, open_pos)
        if close_pos < 0:
            continue

        out_parts.append(text[cursor : open_pos + 1])
        title = text[open_pos + 1 : close_pos]
        normalized = title.replace(" ", "").replace("\n", "")
        if r"\textbf{" in normalized or r"\bfseries" in normalized:
            out_parts.append(title)
        else:
            out_parts.append(r"\textbf{" + title + "}")

        cursor = close_pos

    if not out_parts:
        return text

    out_parts.append(text[cursor:])
    return "".join(out_parts)
