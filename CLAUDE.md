# Skills

## Engineering contract

- The repo root is `Skills/`. Per-person tracker data and generated
  plans live one directory above it and are intentionally not committed.
- Preserve public CLIs, CSV schemas, file locations, and generated output
  semantics unless the PR explicitly documents a migration.
- Public scripts stay thin: parse args, build a `TrackerContext`, call
  domain code, print status/JSON, return an exit code.
- Shared primitives live in `tracker/`; domain storage and import policy
  lives in `shared/`; skill behavior lives in each skill folder.
- One concept gets one source of truth. Do not copy path rules, schema
  constants, CSV I/O, date parsing, capability gates, or exercise catalog
  parsing into another module.
- Optimize by removing wasted work first: repeated reads, repeated full
  scans, duplicate canonicalization, unnecessary rewrites, and reparsing
  static markdown inside one command. Add caching only after measurement.
- Refactors need regression coverage. The default verification command is
  `python3 -m unittest discover -s tests -v` from this directory.
- Privacy rule: committed docs and code comments must not include real
  person names, relationships, locations, ages, medication details, lab
  status, or other profile facts. Use `<Person>` / `<OtherPerson>`
  placeholders. Private context lives only in uncommitted per-person data.
  Before pushing, run the committed-text scrub with a caller-supplied
  sensitive-token pattern:
  `rg -n -i "$PRIVATE_IDENTIFIER_PATTERN" -g '!*.pyc' -g '!plans/**' -g '!<Person>/**' -g '!<OtherPerson>/**' .`
  The pattern value must not be committed.

## Working conventions

- Read [README.md](README.md) for layout and supported workflows, then the relevant skill's `SKILL.md` for behavior.
- Notes contain user-supplied, row-specific annotations. Repeated pipeline metadata belongs in typed columns. Preserve legacy `Source` identities and optional timestamp suffixes when reading existing rows.
- Use canonical title-case exercise names from `shared/exercises-database.md`; aliases belong in the logger reference. Catalog additions require the skill's explicit confirmation flow.
- Manual bodyweight and sleep are opt-in; never prompt for them. Refresh Health Export Kit automatically as the logger skill specifies.
- Each person's `data/` is a separate git repository. One confirmed operation creates one commit; a history failure warns without failing the data write. Never run automatic git garbage collection or repacking. Avoid concurrent writes from multiple synced machines.
- The importer archives successfully consumed JSON exports under `archive/health-exports/YYYY-MM/` unless `--keep-export` is set. It never overwrites a different archived file. Specify the export path when more than one candidate exists.
- Coaching writes assessment JSON before workout markdown and must pass `check_plan.py`. See `workout-coach/SKILL.md` for the recovery gate and planning rules.
