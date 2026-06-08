#!/usr/bin/env python3
"""
strip_lang_fixture.py  -- FIXTURE-PREP UTILITY, *not* engine code.

Removes a customer localisation language layer (e.g. ENZ) from an exported
C/AL object's INLINE multi-language properties, mimicking what the native
cmdlet Remove-NAVApplicationObjectLanguage does to the language file, so that
the known-answer test fixtures match what the production engine actually
operates on (language already stripped at workflow stage 2).

Scope of transformation (inline only):
  CaptionML / OptionCaptionML / TextConst -style bracketed multi-language lists
    Caption=[ENU=...;ENZ=...]   ->  drop the ENZ element
  If ENU (the base/dev language) is the SOLE survivor after the drop, collapse
    [ENU=X]  ->  X        (remove the brackets)
  preserving whatever followed the closing ']'  (';', ' }', or end-of-line).

  When >1 language survives (e.g. a DEU+ENU+ENZ object), brackets are KEPT and
  only the dropped element is removed -- general case, safe for other customers.

This is the ONE place caption lines are touched by regex; the merge engine
never does this. Kept deliberately separate.
"""
import re
import sys

# Language code(s) to strip (customer localisation layer). Base/dev language
# (the sole-survivor collapse target) is ENU. Both are parameters in principle;
# hardcoded here for the fixture set per the census-validated values.
STRIP_CODES = ("ENZ",)
BASE_CODE = "ENU"

# A bracketed multi-language list opens with `<Prop>=[` and runs until the
# matching `]`. Because the list can span multiple physical lines (ENU on one,
# ENZ on the next), we operate on the whole file text, not line-by-line.
#
# Property names that use the bracketed multi-language form:
_PROP = r"(?:Caption|OptionCaption|Caption|Tooltip|InstructionalText|PromotedActionCategories)?ML"
# We match `=[ ... ]` blocks that contain at least one `<CODE>=` token, where
# the codes are 3-letter uppercase language ids. This is deliberately narrow:
# it only fires on language-list brackets, not on arbitrary `[...]`.

_OPEN = re.compile(r"=\[")


def _split_langs(inner: str):
    """Split the inner content of a [ ... ] language list into (code, value)
    pairs. Values may themselves contain commas (OptionCaption!) so we split on
    the `;<CODE>=` boundary, not on bare `;`."""
    # Find `<CODE>=` markers (3 uppercase letters then '='), where a code is
    # either at the very start or preceded by ';' + optional whitespace/newline
    # (multi-line lists put ENZ on its own indented line after `ENU=...;`).
    marker_re = re.compile(r"(?:^|;\s*)([A-Z]{3})=")
    spans = [(m.start(1), m.end(), m.group(1)) for m in marker_re.finditer(inner)]
    if not spans:
        return None  # not a language list
    parts = []
    for i, (code_start, val_start, code) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(inner)
        seg = inner[val_start:end]
        # trim a trailing ';' and any trailing whitespace before the next code
        seg = seg.rstrip()
        if seg.endswith(";"):
            seg = seg[:-1].rstrip()
        parts.append((code, seg))
    return parts


def _promote_lone_strip_code(langs):
    """If the ONLY language present is a strip code (e.g. an ENZ-only caption
    with no ENU base), relabel it to BASE_CODE instead of stripping it -- the
    customer's localised text is the field's only caption, so it becomes the
    base caption. Rule per spec: strip ENZ when an ENU sibling exists; promote
    a lone ENZ to ENU. Returns possibly-modified langs list."""
    if len(langs) == 1 and langs[0][0] in STRIP_CODES:
        return [(BASE_CODE, langs[0][1])]
    return langs


def _process_bracket(inner: str):
    """Given the inner text of a `[...]` language list, return the replacement
    text (WITHOUT brackets if it collapses, WITH brackets otherwise), or None
    if this isn't a language list and should be left untouched."""
    langs = _split_langs(inner)
    if langs is None:
        return None
    promoted = _promote_lone_strip_code(langs)
    changed = promoted != langs
    survivors = [(c, v) for (c, v) in promoted if c not in STRIP_CODES]
    if len(survivors) == len(promoted) and not changed:
        return None  # nothing stripped or promoted; leave original bytes
    if len(survivors) == 1:
        # cmdlet output for a single surviving language keeps the `<CODE>=`
        # prefix and drops the brackets: [ENU=x;ENZ=y] -> ENU=x  (NOT bare x).
        return ("BARE", f"{survivors[0][0]}={survivors[0][1]}")
    # keep brackets, rebuild remaining list in original order
    rebuilt = ";".join(f"{c}={v}" for c, v in survivors)
    return ("BRACKET", rebuilt)


def strip_text(text: str) -> str:
    out = []
    i = 0
    n = len(text)
    while i < n:
        m = _OPEN.search(text, i)
        if not m:
            out.append(text[i:])
            break
        # find matching close bracket
        open_br = m.end() - 1  # index of '['
        close_br = text.find("]", open_br)
        if close_br == -1:
            out.append(text[i:])
            break
        inner = text[open_br + 1:close_br]
        res = _process_bracket(inner)
        if res is None:
            # not a language list (or nothing stripped): emit through the ']'
            out.append(text[i:close_br + 1])
            i = close_br + 1
            continue
        kind, payload = res
        # emit everything up to and including the '=' (drop the '[')
        out.append(text[i:m.start() + 1])  # up through '='
        if kind == "BARE":
            out.append(payload)
        else:
            out.append("[" + payload + "]")
        i = close_br + 1  # skip past original ']'
    return "".join(out)


def _process_textconst(literal: str):
    """literal is the inside of the single quotes of a TextConst, e.g.
    ENU=foo;ENZ=bar  (apostrophes inside appear doubled: '' ). Returns the new
    inner literal, or None if nothing changes. C/AL escapes a single quote as
    '' inside a '..'-quoted string; we split on `;<CODE>=` boundaries the same
    way as brackets, then collapse if ENU is the sole survivor (bare value, no
    enclosing change -- the quotes stay, only the inner list shrinks)."""
    langs = _split_langs(literal)
    if langs is None:
        return None
    promoted = _promote_lone_strip_code(langs)
    changed = promoted != langs
    survivors = [(c, v) for (c, v) in promoted if c not in STRIP_CODES]
    if len(survivors) == len(promoted) and not changed:
        return None
    if len(survivors) == 1:
        return f"{survivors[0][0]}={survivors[0][1]}"   # keep ENU= prefix
    return ";".join(f"{c}={v}" for c, v in survivors)


# TextConst literals: `TextConst '<...>'`. We capture the single-quoted literal,
# allowing doubled '' as an escaped quote so we don't stop early.
_TEXTCONST = re.compile(r"(TextConst\s+')((?:[^']|'')*)(')")


def _strip_textconsts(text: str) -> str:
    def repl(m):
        new_inner = _process_textconst(m.group(2))
        if new_inner is None:
            return m.group(0)
        return m.group(1) + new_inner + m.group(3)
    return _TEXTCONST.sub(repl, text)


# Bare single-language caption: `<Prop>ML=<CODE>=value;` or `... }` with NO
# brackets (only one language present, unbracketed). e.g.
#   CaptionML=ENZ=Orig. Contract Amt. Incl. GST;
# A lone strip-code here is promoted to base then collapses to the bare value:
#   CaptionML=Orig. Contract Amt. Incl. GST;
# A lone ENU here is already bare -> left untouched.
_BARE_CAPTION = re.compile(
    r"((?:Caption|OptionCaption|Tooltip|InstructionalText)ML=)"
    r"([A-Z]{3})="
    r"([^\[\]\r\n}]*)"
)


def _strip_bare_captions(text: str) -> str:
    def repl(m):
        prop, code, val = m.group(1), m.group(2), m.group(3)
        if code in STRIP_CODES:
            # lone strip-code caption (no ENU sibling): promote to base,
            # KEEP the prefix -> CaptionML=ENU=value  (matches cmdlet form)
            return f"{prop}{BASE_CODE}={val}"
        return m.group(0)              # ENU or other: leave exactly as-is
    return _BARE_CAPTION.sub(repl, text)


def main():
    if len(sys.argv) != 3:
        print("usage: strip_lang_fixture.py <in.txt> <out.txt>", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], "r", encoding="cp1252", newline="") as f:
        text = f.read()
    stripped = strip_text(text)
    stripped = _strip_textconsts(stripped)
    stripped = _strip_bare_captions(stripped)
    with open(sys.argv[2], "w", encoding="cp1252", newline="") as f:
        f.write(stripped)
    before = text.count("ENZ=")
    after = stripped.count("ENZ=")
    print(f"{sys.argv[1]} -> {sys.argv[2]}: ENZ {before} -> {after}")


if __name__ == "__main__":
    main()
