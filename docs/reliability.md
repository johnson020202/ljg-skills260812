# Reliability changes

This work follows the 2026-10-19 audit of `7cdcf235f1a26195c37c7abd5b414b6609c50a6f`. It preserves the individual skills and existing CLI entrypoints while strengthening rendering, validation, and publishing. No automatic release, version bump, or user-skill installation is performed by repository checks.

A subsequent integration adds the `book-poster-v3.3.0-windows-qa` changes and the Markdown branch's maintenance skill. See [branch integration](branch-integration.md) for the new 1080px default, portable Windows transaction, 23-skill inventory and full source/Markdown verification. The 436-test result below records the earlier reliability phase, not the final expanded branch-integration test count.

## Reproduce verification

From the repository root:

```sh
python3 scripts/setup.py
python3 scripts/check.py
```

The setup is checkout-local. The full check runs all `*.test.ts` and `test_*.py` suites, existing card/presentation self-checks, shell/Python syntax, repository identity, version consistency, and README inventory. It writes `.cache/check-results.json`; a failed or interrupted invocation cannot leave a previous `pass` as the current report. `--static` is explicitly not full verification.

CI runs the same commands on Ubuntu and macOS. A workflow definition is not proof that a remote CI run has passed; inspect the actual run before release.

## Verified local result (2026-10-19)

The final integrated `python3 scripts/check.py` completed with exit 0 and `scope: full`: **436 tests passed**, plus the existing card audit, presentation self-test, repository contracts and syntax checks.

| Suite | Tests |
|---|---:|
| book | 78 |
| is | 73 |
| blind (Bun + Python) | 28 |
| classic | 91 |
| card browser/image tests | 12 |
| present | 67 |
| book-poster | 36 |
| publishing + root setup/check | 51 |
| **Total** | **436** |

The first integrated attempt exposed a test-fixture shebang that did not support a Python virtualenv path containing spaces. It was corrected to use the fixture's explicitly controlled PATH, and setup plus the entire integrated check were rerun successfully; no suite was skipped to obtain a pass.

Independent reviewer findings were fixed and replayed. Original audit fixtures were also run through the real CLIs: the previously missing card footer is visible, tall poster crops match the main image byte-for-byte after decoding, missing fonts fail explicitly, stale sections are absent, and bad classic/presentation inputs are rejected. Local logs remain in `.cache/check/`, with machine-readable reports in `.cache/check-results.json` and `.cache/test-summary.json`.

These results record the local verification phase before publication, not a claim that GitHub CI or a release had already run at that point. The implementation was prepared on `fix/reliability-audit-20261019`; release 1.21.0 / poster tag v3.3.0 publishes it separately. No installed-skill replacement is part of this release.

## Audit-to-test map

| Audit IDs | Corrected contract | Regression coverage |
|---|---|---|
| REL-01 | Dry-run is read-only; no checkout/reset of the user's workspace | `scripts/test_publish.py` |
| REL-02 | Skill names, canonical paths, symlinks and source traversal errors fail closed | `scripts/test_publish.py` |
| REL-03 | Dirty worktrees/indexes rejected; only explicit managed paths can be committed | `scripts/test_publish.py` |
| REL-04 | Exact repository identity, source branch, expected remote SHA and explicit atomic refspecs | `scripts/test_publish.py` |
| REL-05 | Structured collection version changes are verified in files and generated commits | `scripts/test_publish.py` |
| REL-06 | Markdown manual content/metadata drift rejected rather than overwritten | `scripts/test_publish.py` |
| REL-07–08 | Fork identity and complete README skill inventory | `scripts/test_check.py`; publishing tests |
| REN-01–02 | Scale-aware device budget; main image is the only pixel source; manifest-ordered crops | `skills/ljg-book-poster/scripts/test_render.py` |
| REN-03 | Required resource failure is an error; all cached fonts have SHA validation | `skills/ljg-book-poster/scripts/test_render.py` |
| REN-04–06 | Visible text clipping, cross-inline final lines, markers and shrinking transforms checked | `skills/ljg-book-poster/scripts/test_audit.py` |
| REN-07–08 | Encoded filenames, explicit HTTP failure, meaningful exit codes, bounded threaded HTTP cleanup | `skills/ljg-book-poster/scripts/test_render.py` |
| CLS-01–02 | Input/output aliases rejected; staged artifact publication rolls back ordinary failures | `skills/ljg-classic/Tools/RenderClassic.test.ts` |
| CLS-03 | Annotation coverage uses genuine text/punctuation classification | `skills/ljg-classic/Tools/RenderClassic.test.ts` |
| CLS-04–05 | Required schema v2 fields; PNG container checks plus bounded real decoding | `skills/ljg-classic/Tools/RenderClassic.test.ts` |
| VIS-01, VIS-03 | Fixed viewport capture; lazy images load before capture; bounded failure preserves old output | `skills/ljg-card/tests/capture.test.ts`; `png-strips.test.ts` |
| VIS-02, VIS-04–05 | Finished decks reject placeholders; all scripts/styles/resources inspected with real JS parsing | `skills/ljg-present/tests/validate-deck.test.ts` |
| VIS-06 | Finite math syntax has single-token unbraced scripts; unsupported syntax stays literal | presentation tests and `skills/ljg-card/tests/deck-browser.test.ts` |
| TXT-01–03 | Contextual source-label detection, same-line nonempty metadata, nonempty evidence zones | `skills/ljg-book/scripts/validate_note.test.ts` |
| TXT-04 | Actual YAML frontmatter parsing, decoded metadata and placeholder checks | `skills/ljg-is/Tools/ValidateNote.test.ts` |
| TXT-05–07 | Host/root-aware message extraction, local-day time intervals, message-level noise filtering | `skills/ljg-blind/Tools/test_extract_conversations.py` |
| TXT-08 | Tools resolve relative to the loaded skill, including project-local installs with spaces | `skills/ljg-blind/Tools/WeReadWebUrl.test.ts`; workflow commands |

Independent review also added regression coverage for case-insensitive/Unicode path aliases, unmanaged QA filename collisions, PNG CRC/IEND/APNG handling, bounded hashing, publishing source-scan failures, legacy metadata drift, file↔directory release changes, HTML entities, Script/Module parsing targets, and quoted system-tag examples.

## Rendering and artifact contracts

### Book posters

- Layout uses a fixed viewport. Each browser capture stays within a 12000-device-pixel budget, with scale-aligned boundaries.
- Exactly one DOM audit supplies both the report and crop coordinates.
- Sections, sheets and thumbnails are derived from the assembled main PNG rather than separate browser captures.
- Resource errors fail with exit `2`; blocking content problems return `1`; a clean render returns `0`.
- `poster.py` builds its full output group privately, validates images, then switches the managed generation pointer.
- Public output names are symlinks. **Deliver a dereferenced copy of a PNG, not a standalone symlink.** For example, `cp -L out/book.png delivery/book.png` copies its bytes. Do not publish a resolved internal generation path as a durable URL; it may be cleaned on the next successful render.
- The first migration from old regular outputs keeps a legacy backup and supports exception rollback. It is not a crash/kill-proof multi-file migration. Readers crossing multiple concurrent publications do not get a persistent snapshot simply by resolving a generation once.
- `CHROMIUM_PATH` remains an explicit user override for direct CLI use. Repository verification removes it and uses the Playwright-matched browser.

### Classic artifacts

- Preflight rejects conflicting inputs, outputs, resources and generated-slice targets, including relevant filesystem aliases.
- Ordinary errors during generation or commit roll back previous outputs. This is not a database transaction against power loss, `SIGKILL`, or malicious concurrent filesystem replacement.
- Existing schema v2 artifacts missing required rendering fields are rejected. There is no silent legacy downgrade; regenerate old artifacts with the current renderer.
- PNG structure/CRC validation and actual bounded decoding are both required. Animated inputs are rejected for deterministic capture.
- A manifest establishes internal file consistency, not independent proof of content meaning or rendering provenance.

### Cards and presentations

- Card captures retain their original layout viewport while taking bounded strips; Chromium 8-bit RGB/RGBA strip output is supported, with a 64MP output limit.
- The input HTML is not modified when substituting the logo. Output replacement happens only after successful rendering.
- Presentation validation uses exact, module-local Acorn and HTML entity dependencies. The generated deck itself remains offline and does not require those tools.
- Static resource inspection is a template contract check, not an arbitrary JavaScript sandbox or complete data-flow proof. Actual offline rendering/navigation is also covered by browser regression tests.

## Publishing behavior changes

Both shell publishing entrypoints use one Python implementation. It checks a clean source repository, explicit identity and branch state; builds commits in owned temporary storage; verifies generated trees; and uses a single explicit atomic push with expected ref values.

Tests never perform real network transport: Git network commands are stubbed, hooks/config/HOME are isolated, and local protocol access is additionally denied. Real authentication and a server's atomic-push support are not proven by those tests.

A legacy `md` branch with manual changes is deliberately refused. Only the three defined collection release-version fields may differ during migration; unrelated JSON fields, plugin entries, modes or skill content are not silently discarded. Migrate such changes explicitly before publishing. A dirty implementation branch is also deliberately not publishable until its intended changes have been reviewed and committed by an authorized action.

## Dependency and portability boundaries

- Bun 1.3.14 is the verified baseline. Each TypeScript skill that needs packages owns its frozen lockfile.
- Classic retains Playwright 1.62.1 and adds sharp 0.34.5 for real image decoding. Card retains Playwright 1.58.2.
- Book-poster directly pins Playwright 1.58.0 and Pillow 11.3.0. This is not a hash-locked transitive Python dependency set.
- Rendering checks use the matching local browser cache, not an arbitrary system Chrome. Setup disables browser cache garbage collection while installing multiple module versions.
- Python 3.9+ is supported by the source; the integrated rendering environment and CI use Python 3.12.
- macOS arm64 was the local execution environment. Linux CI is configured but is not represented as already executed. Windows is not a verified full-rendering platform; publication uses POSIX-specific filesystem behavior.

## Performance measurement

A fixed synthetic six-section poster (1440 CSS px wide, 8880 CSS px tall, 2x output) was rendered three times per implementation on the same machine, Python 3.12.12, Playwright 1.58.0, Pillow 11.3.0 and Chromium headless-shell 1208 / 145.0.7632.6, with no remote resources.

| Metric | Audited baseline | Updated renderer |
|---|---:|---:|
| End-to-end wall time, median of 3 | 4.969 s | 3.203 s |
| Main PNG bytes | 337337 | 348896 |
| Browser captures | 2 main + 6 sections | 2 main |
| Full DOM audits | 2 | 1 |

The main PNGs were pixel-identical after decoding. This fixture's median runtime fell **35.5%**, while PNG size grew **3.4%**. It is a single-fixture result, not a general speedup promise; peak memory was not measured. High scale may require more safe strips than the baseline's unsafe fixed CSS step.
