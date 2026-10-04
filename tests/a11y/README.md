# Accessibility tests of web UI v2

The browser suite in this directory (`pytest tests/a11y -m a11y`) checks web UI
v2 against BITV 2.0 / EN 301 549 / WCAG 2.1 A+AA. What it covers and how is
described in [docs/ACCESSIBILITY.md](../../docs/ACCESSIBILITY.md).

## Optional LLM review (advisory)

Some test steps depend on what a text *means*, which a browser cannot decide:

| Step | Question |
|---|---|
| 9.1.1.1 | Does a text alternative describe the image's purpose? |
| 9.1.3.3 | Do instructions rely only on shape, colour, size, position or sound? |
| 9.2.4.4 | Is a link's purpose clear from its name and context? |
| 9.2.4.6 | Do headings and labels describe their topic or purpose? |
| 9.3.3.2 | Are labels and instructions sufficient? |
| 9.3.3.3 | Do error messages say how to correct the input? |
| translation | Does a translation change the meaning compared with English? |

`llm_review.py` asks Claude for a second opinion on these. It starts the app as
the suite does, opens every v2 page in every UI language (all disclosures
open), extracts the title, headings, links (name, target, context), control
names, form labels/placeholders/descriptions, image alternatives, visible
instruction sentences and the error/status messages shown after submitting
each visible form empty, and sends that as compact JSON with a fixed rubric to
the Messages API (one request per page and language, plus one translation
comparison per page).

```sh
pip install -e '.[web,a11y]' && playwright install chromium
export ANTHROPIC_API_KEY=...
python -m tests.a11y.llm_review --out a11y-llm-review.json
```

Options: `--pages audit,kb`, `--langs en,de`, `--effort high`, `--max-requests 60`
and `--max-cost 10` (USD, estimated from the reported token usage; the run stops
sending once either limit is reached), `--dry-run` (collect the page data and
build the requests without calling the API; no key needed).

The output looks like:

```json
{"generated_at": "…", "model": "claude-opus-5-5",
 "pages": [{"task": "page", "page": "audit", "lang": "en", "status": "reviewed", "findings": 1, "data": {…}}, …],
 "steps": {"9.3.3.3": {"verdict": "issues",
                       "findings": [{"page": "…", "lang": "…", "element": "…", "problem": "…", "suggestion": "…"}]}, …}}
```

`verdict` is `ok`, `issues`, or `not-reviewed` (no answer was received for
that step, e.g. in a dry run).

**This is advisory.** The findings are a model's opinion for a human tester to
confirm or reject; they are not test results and do not decide any BITV step.
The script never asserts and always exits 0. Without `ANTHROPIC_API_KEY` it
prints a notice and does nothing.

Notes:

- Model: `claude-opus-5-5`. It accepts no sampling parameters
  (`temperature` is rejected), so results can vary slightly between runs; the
  fixed rubric, sorted input and a JSON-schema-constrained answer
  (`output_config.format`) keep them as stable as possible.
- The rubric is the system prompt and is prompt-cached, so only the first
  request pays for it in full.
- Retries: 408/409/429/5xx/529 and network errors, with exponential backoff
  (honours `retry-after`). Refusals are re-run on Anthropic's recommended
  fallback model (`fallbacks: "default"`); a remaining refusal is recorded as an
  error for that page.
- Only the standard library, httpx and Playwright are used (no SDK).
- The pure parts (compaction, request building, response parsing, client
  retries, cost guard) are tested offline in `tests/test_a11y_llm_review.py`.
- In CI the informational a11y job runs it only when the `ANTHROPIC_API_KEY`
  secret is set and uploads `a11y-llm-review.json`.
