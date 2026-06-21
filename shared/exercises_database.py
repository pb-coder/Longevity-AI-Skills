"""Parse, lookup, fuzzy-match, and safely extend the canonical exercises
catalog at ``Skills/shared/exercises-database.md`` plus the alias table
at ``Skills/workout-logger/references/aliases.md``.

Used by ``/log`` (workout-logger) to detect unknown exercises and add
them safely after agent-driven research. Used by ``/coach`` indirectly
(via the existing parser in ``workout-coach/lib/extract.py``) for muscle
mapping.

Public surface:

- ``parse_database()`` → structured dict (muscle → section → list of entries).
- ``parse_aliases()`` → list of alias rows.
- ``lookup(name)`` → canonical name (alias-aware, case-insensitive) or None.
- ``known_name_set()`` → normalized canonical + alias-input names.
- ``is_known_name(name)`` → True when a name is canonical or an alias input.
- ``fuzzy_match(name, k=3)`` → top-K (canonical, similarity_0_to_1) pairs.
- ``propose_exercise(...)`` → atomic write of a new entry into the
  appropriate section, with post-write re-parse to guarantee no
  corruption.
- ``propose_alias(...)`` → atomic append of an alias row.
- ``validate_database()`` → re-parses both files and returns a list of
  issues (empty list = clean).

CLI (the workout-logger agent invokes these at /log time):

    python3 exercises_database.py lookup "Belt Squat Machine"
    python3 exercises_database.py fuzzy "belt squad" --k 5
    python3 exercises_database.py propose --from-stdin    # reads JSON
    python3 exercises_database.py validate
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent  # Skills/
DATABASE_PATH = _REPO / "shared" / "exercises-database.md"
ALIASES_PATH = _REPO / "workout-logger" / "references" / "aliases.md"


# ============================================================ Parser
_MUSCLE_HEADING_RE = re.compile(r"^##\s+([A-Z][A-Z /]+)\s*$")
_SECTION_HEADING_RE = re.compile(r"^###\s+(.+)$")
_ENTRY_RE = re.compile(r"^-\s+(.+)$")


def parse_database() -> dict:
    """Walk the catalog markdown into ``{muscle: {section: [entries]}}``.

    Each entry is the raw line content (after the leading ``- ``), so
    callers can preserve the original formatting on rewrite. Section
    headings are kept in document order via ``__order__`` lists.
    """
    text = DATABASE_PATH.read_text(encoding="utf-8")
    out: dict = {"__muscle_order__": [], "muscles": {}}
    current_muscle: str | None = None
    current_section: str | None = None

    # Sentinel for entries that appear directly under ``## MUSCLE`` with
    # no ``### Section`` heading (CARDIO, NECK, ADDUCTORS, CALVES,
    # WELLNESS at time of writing).
    DEFAULT_SECTION = "_default"

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m = _MUSCLE_HEADING_RE.match(line)
        if m:
            current_muscle = m.group(1).strip()
            current_section = DEFAULT_SECTION
            if current_muscle not in out["muscles"]:
                out["__muscle_order__"].append(current_muscle)
                out["muscles"][current_muscle] = {
                    "__section_order__": [],
                    "sections": {},
                }
            continue
        if current_muscle is None:
            continue
        s = _SECTION_HEADING_RE.match(line)
        if s:
            current_section = s.group(1).strip()
            mb = out["muscles"][current_muscle]
            if current_section not in mb["sections"]:
                mb["__section_order__"].append(current_section)
                mb["sections"][current_section] = []
            continue
        if current_section is None:
            continue
        e = _ENTRY_RE.match(line)
        if not e:
            continue
        # Lazily register the default section the first time it's needed
        # so muscles without any direct entries don't get a stub section.
        mb = out["muscles"][current_muscle]
        if current_section == DEFAULT_SECTION and \
                DEFAULT_SECTION not in mb["sections"]:
            mb["__section_order__"].insert(0, DEFAULT_SECTION)
            mb["sections"][DEFAULT_SECTION] = []
        # Skip entries inside parenthetical info blocks
        # ("(Biceps receive ~0.5 sets …)") which are pure prose.
        if line.strip().startswith("(") or "receive" in line.lower():
            continue
        out["muscles"][current_muscle]["sections"][current_section].append(
            e.group(1).strip()
        )
    return out


def _entry_canonical_name(entry_line: str) -> str:
    """Extract the canonical exercise name from an entry line.

    Entry shape examples:
      ``Cable Lateral Raise [Cable] ◆``
      ``Pull-Up [BW] — +biceps ◆``
      ``Conventional Deadlift [BB] — +glutes, +hamstrings, +erectors (primary: posterior chain)``

    The name is everything before the first ``[`` (which opens the
    equipment tag block).
    """
    bracket_idx = entry_line.find("[")
    if bracket_idx == -1:
        return entry_line.split(" — ")[0].strip()
    return entry_line[:bracket_idx].strip()


def _all_canonical_names() -> list[str]:
    """Flat list of every canonical exercise name from the database."""
    db = parse_database()
    out: list[str] = []
    for muscle in db["__muscle_order__"]:
        for section in db["muscles"][muscle]["__section_order__"]:
            for entry in db["muscles"][muscle]["sections"][section]:
                out.append(_entry_canonical_name(entry))
    return out


# ============================================================ Aliases
def parse_aliases() -> list[dict]:
    """Return the alias rows from ``aliases.md``.

    Each row: ``{"inputs": [user_input1, ...], "canonical": "...", "notes": "..."}``.
    The first table column accepts comma-separated alternatives.
    """
    if not ALIASES_PATH.exists():
        return []
    text = ALIASES_PATH.read_text(encoding="utf-8")
    rows: list[dict] = []
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("|---"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Aliases table is 3 cells: user_input | canonical | notes.
        # The Equipment Defaults table is 2 cells: context | default. Skip.
        if len(cells) != 3:
            continue
        # Skip the header row of any subsequent 3-cell table.
        if cells[0].lower() in ("user input", "context"):
            continue
        inputs = [s.strip() for s in cells[0].split(",") if s.strip()]
        canonical = cells[1].strip()
        notes = cells[2].strip()
        if not inputs or not canonical:
            continue
        rows.append({"inputs": inputs, "canonical": canonical, "notes": notes})
    return rows


# ============================================================ Lookup
def _normalize_for_match(name: str) -> str:
    """Lowercase + collapse whitespace + strip trailing punctuation."""
    n = " ".join(name.lower().split())
    return n.rstrip(".:;,")


def lookup(name: str) -> str | None:
    """Resolve a user-typed exercise name to its canonical form.

    Priority:
      1. Exact (case-insensitive) match against a database entry.
      2. Exact (case-insensitive) match against an alias's ``inputs``.
      3. Returns ``None`` when nothing matches — the caller can fall
         through to fuzzy_match / proposal flow.
    """
    if not name or not name.strip():
        return None
    target = _normalize_for_match(name)

    for canonical in _all_canonical_names():
        if _normalize_for_match(canonical) == target:
            return canonical

    for row in parse_aliases():
        for inp in row["inputs"]:
            if _normalize_for_match(inp) == target:
                return row["canonical"]
    return None


def known_name_set() -> set[str]:
    """Return normalized canonical names and alias inputs.

    Use this when a caller needs many membership checks in one command.
    It avoids repeatedly parsing the catalog and aliases for each row.
    """
    names = {_normalize_for_match(n) for n in _all_canonical_names()}
    for row in parse_aliases():
        names.update(
            _normalize_for_match(inp)
            for inp in row.get("inputs", [])
        )
    return names


def is_known_name(name: str, known_names: set[str] | None = None) -> bool:
    """True when ``name`` is canonical or an alias input."""
    if not name or not name.strip():
        return False
    names = known_names if known_names is not None else known_name_set()
    return _normalize_for_match(name) in names


def _per_token_match_avg(query_tokens: list[str],
                         canonical_tokens: list[str]) -> float:
    """Average best-match score for each query token against all canonical tokens.

    For each query token, find the highest SequenceMatcher ratio against any
    canonical token and average those bests. This correctly handles abbreviated
    query tokens like "lat" matching "lateral" much better than "leg", even
    though at the whole-string level both "leg raise" and "lateral raise"
    share the substring "raise" with "lat raise".
    """
    if not query_tokens or not canonical_tokens:
        return 0.0
    total = 0.0
    for qt in query_tokens:
        best = max(
            difflib.SequenceMatcher(None, qt, ct).ratio()
            for ct in canonical_tokens
        )
        total += best
    return total / len(query_tokens)


def fuzzy_match(name: str, k: int = 3) -> list[tuple[str, float]]:
    """Return top-K (canonical, similarity_0_to_1) pairs against the database.

    Blends ``difflib.SequenceMatcher`` whole-string ratio (30%) with a
    per-token best-match average (70%). The blend down-weights false
    positives from pure sequence matching — e.g. "lat raise" previously
    matched "Leg Raise" above "Lateral Raise" because the character
    sequence similarity was high. Per-token matching correctly identifies
    "lat" as a closer prefix of "lateral" than "leg".

    The caller can apply a threshold (e.g. ``≥ 0.85`` → propose as alias of
    the top hit rather than a new exercise).
    """
    if not name or not name.strip():
        return []
    target = _normalize_for_match(name)
    target_tokens = target.split()
    scored: list[tuple[str, float]] = []
    for canonical in _all_canonical_names():
        norm_canonical = _normalize_for_match(canonical)
        canonical_tokens = norm_canonical.split()
        seq_ratio = difflib.SequenceMatcher(None, target, norm_canonical).ratio()
        tok_ratio = _per_token_match_avg(target_tokens, canonical_tokens)
        blended = round(0.3 * seq_ratio + 0.7 * tok_ratio, 3)
        scored.append((canonical, blended))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


# ============================================================ Validation
def validate_database() -> list[str]:
    """Return a list of issues with the database + aliases markdown.

    Empty list means clean. Catches: missing muscle headings, sections
    without parent muscle, duplicate canonical names (case-insensitive),
    alias rows pointing to a non-existent canonical name, and parse-time
    crashes.
    """
    issues: list[str] = []
    try:
        names = _all_canonical_names()
    except Exception as exc:  # pragma: no cover — defensive
        return [f"database parse failure: {exc!r}"]

    # Duplicate canonicals.
    seen: dict[str, int] = {}
    for n in names:
        key = _normalize_for_match(n)
        seen[key] = seen.get(key, 0) + 1
    for k, v in seen.items():
        if v > 1:
            issues.append(
                f"duplicate canonical name: {k!r} appears {v} times"
            )

    # Aliases pointing nowhere.
    canonical_set = {_normalize_for_match(n) for n in names}
    for row in parse_aliases():
        target = _normalize_for_match(row["canonical"])
        if target not in canonical_set:
            issues.append(
                f"alias points to non-existent canonical: "
                f"{row['inputs']!r} → {row['canonical']!r}"
            )
    return issues


# ============================================================ Writers
def _atomic_write(path: Path, content: str) -> None:
    """Tmp + rename so a crash mid-write can't truncate the canonical file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _validate_or_rollback(path: Path, prior_content: str) -> list[str]:
    """Re-parse after a write. If issues surface, restore prior content."""
    issues = validate_database()
    if issues:
        path.write_text(prior_content, encoding="utf-8")
        return [f"WRITE ROLLED BACK due to validation failures:"] + issues
    return []


def _format_entry_line(name: str, tags: list[str]) -> str:
    """Render an entry line in the catalog's house style.

    - Equipment tag (e.g. ``[Machine]``) directly after the name.
    - Synergist tags (``+muscle``) joined with commas, prefixed by ``— ``.
    - Lengthened-position flag ``◆`` at the end if present.
    """
    eq_tags = [t for t in tags if t.startswith("[")]
    syn_tags = [t for t in tags if t.startswith("+")]
    flag_tags = [t for t in tags if t == "◆"]
    pieces = [name]
    if eq_tags:
        pieces.append(eq_tags[0])  # one equipment tag per entry
    line = " ".join(pieces)
    if syn_tags:
        line += " — " + ", ".join(syn_tags)
    if flag_tags:
        line += " ◆"
    return f"- {line}"


def propose_exercise(name: str, primary_muscle: str, section: str,
                     tags: list[str]) -> dict:
    """Add a new exercise entry to the catalog. Idempotent.

    - If an entry with the same canonical name already exists, no write
      happens and the call returns ``{"action": "noop"}``.
    - On success, the file is re-parsed; any validation failure rolls
      back the write.

    Returns a dict ``{"action": "added"|"noop"|"error", "details": ...}``.
    """
    canonical = name.strip()
    if not canonical:
        return {"action": "error", "details": "empty name"}

    if lookup(canonical):
        return {"action": "noop", "details": f"already canonical: {canonical}"}

    primary_muscle = primary_muscle.strip().upper()
    section = section.strip()

    prior = DATABASE_PATH.read_text(encoding="utf-8")
    db = parse_database()

    if primary_muscle not in db["muscles"]:
        return {
            "action": "error",
            "details": f"unknown primary muscle heading: {primary_muscle!r}. "
                       f"Known: {db['__muscle_order__']!r}",
        }

    muscle_block = db["muscles"][primary_muscle]
    if section not in muscle_block["sections"]:
        return {
            "action": "error",
            "details": f"unknown section under {primary_muscle}: "
                       f"{section!r}. Known: {muscle_block['__section_order__']!r}",
        }

    new_line = _format_entry_line(canonical, tags)

    # Find the section's last entry line and insert the new line after
    # it. We re-walk the raw file to preserve formatting precisely.
    lines = prior.splitlines()
    in_muscle = False
    in_section = False
    insert_at: int | None = None
    for i, raw in enumerate(lines):
        if _MUSCLE_HEADING_RE.match(raw):
            muscle_match = _MUSCLE_HEADING_RE.match(raw).group(1).strip()
            in_muscle = muscle_match == primary_muscle
            in_section = False
            continue
        if not in_muscle:
            continue
        if _SECTION_HEADING_RE.match(raw):
            sec_match = _SECTION_HEADING_RE.match(raw).group(1).strip()
            if in_section and insert_at is None:
                # We just left the target section without finding a slot;
                # insert at the section's last entry before this heading.
                insert_at = i
                break
            in_section = sec_match == section
            continue
        if in_section and _ENTRY_RE.match(raw):
            insert_at = i + 1  # keep walking — we want the LAST entry slot

    if insert_at is None:
        return {
            "action": "error",
            "details": f"could not locate section {section!r} under "
                       f"{primary_muscle!r}",
        }

    new_lines = lines[:insert_at] + [new_line] + lines[insert_at:]
    new_content = "\n".join(new_lines)
    if prior.endswith("\n") and not new_content.endswith("\n"):
        new_content += "\n"
    _atomic_write(DATABASE_PATH, new_content)

    rollback_issues = _validate_or_rollback(DATABASE_PATH, prior)
    if rollback_issues:
        return {"action": "error", "details": rollback_issues}

    return {
        "action": "added",
        "details": {
            "canonical_name": canonical,
            "muscle": primary_muscle,
            "section": section,
            "line": new_line,
        },
    }


def propose_alias(user_input: str, canonical_name: str,
                  notes_modifier: str | None = None) -> dict:
    """Append an alias row to the alias table. Idempotent.

    - Verifies ``canonical_name`` exists (case-insensitive) in the
      database first; refuses to write an alias pointing nowhere.
    - If the same ``user_input`` already maps to the same canonical,
      returns ``{"action": "noop"}``.
    - On success, re-validates both files.
    """
    user_input = user_input.strip()
    canonical_name = canonical_name.strip()
    if not user_input or not canonical_name:
        return {"action": "error", "details": "empty input or canonical"}

    if lookup(canonical_name) is None:
        return {
            "action": "error",
            "details": f"canonical {canonical_name!r} not in database",
        }
    # Resolve to the actual canonical casing.
    canonical_resolved = lookup(canonical_name) or canonical_name

    existing = lookup(user_input)
    if existing and _normalize_for_match(existing) == _normalize_for_match(canonical_resolved):
        return {
            "action": "noop",
            "details": f"{user_input!r} already aliases to {canonical_resolved!r}",
        }
    if existing:
        return {
            "action": "error",
            "details": f"{user_input!r} already aliases to {existing!r}; "
                       f"refusing to overwrite. Edit aliases.md manually if intended.",
        }

    prior = ALIASES_PATH.read_text(encoding="utf-8")
    notes_cell = notes_modifier.strip() if notes_modifier else "—"
    new_row = f"| {user_input} | {canonical_resolved} | {notes_cell} |"

    # Insert after the last existing alias row before the next blank
    # line / next heading. Walk lines.
    lines = prior.splitlines()
    in_table = False
    insert_at: int | None = None
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("|---"):
            in_table = True
            continue
        if in_table and not stripped.startswith("|"):
            insert_at = i
            break
        if in_table:
            insert_at = i + 1
    if insert_at is None:
        return {
            "action": "error",
            "details": "couldn't find the alias table body",
        }
    new_lines = lines[:insert_at] + [new_row] + lines[insert_at:]
    new_content = "\n".join(new_lines)
    if prior.endswith("\n") and not new_content.endswith("\n"):
        new_content += "\n"
    _atomic_write(ALIASES_PATH, new_content)

    issues = validate_database()
    if issues:
        ALIASES_PATH.write_text(prior, encoding="utf-8")
        return {
            "action": "error",
            "details": ["WRITE ROLLED BACK — alias write broke validation:"] + issues,
        }
    return {
        "action": "added",
        "details": {
            "user_input": user_input,
            "canonical": canonical_resolved,
            "notes": notes_cell,
        },
    }


# ============================================================ CLI
def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_lookup = sub.add_parser("lookup", help="Resolve a user-typed name to canonical.")
    p_lookup.add_argument("name")

    p_fuzzy = sub.add_parser("fuzzy", help="Top-K fuzzy matches against the catalog.")
    p_fuzzy.add_argument("name")
    p_fuzzy.add_argument("--k", type=int, default=3)

    p_validate = sub.add_parser("validate", help="Re-parse + report issues.")

    p_propose = sub.add_parser(
        "propose", help="Add an entry or alias from a structured JSON proposal."
    )
    p_propose.add_argument(
        "--from-stdin", action="store_true",
        help="Read the proposal JSON from stdin (recommended).",
    )
    p_propose.add_argument(
        "--json", type=str,
        help="Path to a JSON file containing the proposal.",
    )

    args = p.parse_args()

    if args.cmd == "lookup":
        canonical = lookup(args.name)
        if canonical is None:
            print("UNKNOWN", file=sys.stdout)
            return 1
        print(canonical)
        return 0

    if args.cmd == "fuzzy":
        for name, score in fuzzy_match(args.name, k=args.k):
            print(f"{score:.3f}\t{name}")
        return 0

    if args.cmd == "validate":
        issues = validate_database()
        if not issues:
            print("validate: clean")
            return 0
        for issue in issues:
            print(f"validate: {issue}", file=sys.stderr)
        return 1

    if args.cmd == "propose":
        if args.from_stdin:
            payload = json.load(sys.stdin)
        elif args.json:
            payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
        else:
            print("--from-stdin or --json required", file=sys.stderr)
            return 2

        kind = payload.get("kind")
        if kind == "exercise":
            result = propose_exercise(
                name=payload["name"],
                primary_muscle=payload["primary_muscle"],
                section=payload["section"],
                tags=payload.get("tags", []),
            )
        elif kind == "alias":
            result = propose_alias(
                user_input=payload["user_input"],
                canonical_name=payload["canonical_name"],
                notes_modifier=payload.get("notes_modifier"),
            )
        else:
            print(f"unknown kind: {kind!r}; expected 'exercise' or 'alias'",
                  file=sys.stderr)
            return 2

        print(json.dumps(result, indent=2))
        return 0 if result["action"] in ("added", "noop") else 1

    return 2


if __name__ == "__main__":
    sys.exit(_cli())
