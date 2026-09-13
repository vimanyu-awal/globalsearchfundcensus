# Global Search Fund Census (ex-North America)

A free, public census of search funds and ETA vehicles across all geographies outside the United States and Canada. Built as a **Kellogg Zell Fellows give-back project**. Non-commercial; attribution appreciated.

**Current coverage:** 162 entries · 31 countries · 4 regions · release 2026-09. The IESE 2024 International Search Fund Study counts ~320 international funds; roughly 145 remain publicly unnameable and require direct outreach to the IESE Search Fund Center (contact: Juan Naranjo, jnaranjo@iese.edu).

---

## Files

| File | What it is |
|---|---|
| `census_data.json` | Canonical dataset — single source of truth (schema v1.0; `added_in` marks the release each entry joined) |
| `global_sf_census_final.xlsx` | Formatted workbook (Census · Summary · Legend); also embedded in the dashboard's Download menu |
| `index.html` | The deployed dashboard (identical to `global_sf_census_dashboard.html`) |
| `global_sf_census_dashboard.jsx` | React dashboard with the data embedded |
| `migration_changelog.csv` | Audit trail of every field change made during the v1.0 schema migration |
| `DATA_AUDIT.md` | Issues log (severity-rated), migration summary, QA report |
| `CONTRIBUTING.md` | How the community submits corrections + new entries |

---

## Data dictionary (schema v1.0)

Every entry in `census_data.json → entries[]`:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable slug: `{iso2}-{fund-slug}`. Never reuse or rename. |
| `fund_name` | string \| null | Legal/known vehicle name. `null` = not public. |
| `searchers[]` | array | `{name, education, linkedin}` per principal. Empty array = searcher not public. |
| `searcher_display` | string \| null | Pre-joined display string. |
| `partnered` | bool | True = 2+ principals. |
| `model_type` | enum | `traditional` \| `self_funded` \| `accelerator` |
| `status` | enum | `raising` \| `searching` \| `operating` \| `exited` \| `pivoted` \| `search_ended` |
| `status_as_of` | YYYY-MM | When status was last verified. Drives staleness badges. |
| `vintage` / `vintage_approx` | int / bool | Year fund launched; approx flag preserves "~2022"-style source data. |
| `searcher_origin_country` | string | Where the searcher(s) are from/based. |
| `search_geography[]` | array | Countries where the fund searches/acquired. **Region is derived from this, not from origin.** |
| `primary_country` | string | Map pin location. |
| `region` | enum | `Europe` \| `Latin America` \| `Asia-Pacific` \| `Africa & Middle East` |
| `cross_border` | bool | origin ≠ search geography (e.g. Alerce: Chile → UK). |
| `acquisition` | object \| null | `{company, year, sector, deal_ev, entry_ebitda, entry_multiple}` |
| `exit` | object \| null | `{year, buyer, moic, type}` — `type: "partial"` for partial exits (e.g. CTAIMA/Hg). |
| `investors` | object | `{institutional[], individuals}` — institutional list is structured; individuals is free text. |
| `confidence` | enum | `high` (2+ independent sources) \| `medium` (1 primary source) \| `low` (investor-page/IESE listing only) |
| `coords` | object | `{lat, lng, precision: "city"|"country"}` — country-precision pins are centroid + deterministic jitter. |
| `notes` | string \| null | Context, sources, flags. `STAGE-1 UPDATE:` prefixes mark research-pass changes. |

**Conventions:**
- Unknown = `null`, rendered as "—". Never guessed, never fabricated.
- `search_ended` = search concluded without a publicly confirmed acquisition (e.g., Relay marks the vehicle "Past Search Fund", or the principal demonstrably moved on). Outcome may simply be unverified — the notes say which.
- Region follows **where capital is deployed**, not searcher nationality. This diverges from IESE's origin-based counting for a handful of cross-border funds — flagged in DATA_AUDIT.md.

---

## Update workflow

1. **Intake** — corrections arrive via GitHub issues or the Google Form (see CONTRIBUTING.md). Triage weekly/monthly.
2. **Verify** — require at least one public source (press, investor portfolio page, LinkedIn, registry). One source → `medium` confidence ceiling; two independent → `high`.
3. **Edit `census_data.json`** — the JSON is the single source of truth. Update `status_as_of` whenever you touch `status`. Append a row to `migration_changelog.csv` (entry_id, field, old, new, reason).
4. **Regenerate the dashboard** — either:
   - re-inject: `python -c "import json; tpl=open('dashboard_template.jsx').read(); print(tpl.replace('__CENSUS_DATA__', json.dumps(json.load(open('census_data.json')), separators=(',',':'))))" > global_sf_census_dashboard.jsx`, or
   - in a hosted deployment, have the app `fetch('./census_data.json')` at load so the JSX never needs regeneration.
5. **Run QA** — `node qa.js` validates enums, ID uniqueness, year ordering, coordinate ranges, and all filter combinations.

## Hosting (no backend required)

Drop into a Vite React app, put `census_data.json` in `/public`, swap the embedded `CENSUS` const for a `fetch`. Deploys free on GitHub Pages / Netlify / Vercel. The dashboard is pure client-side and tested against 500 synthetic entries.

## Handoff notes

- The biggest data gap is **structural**: ~145 IESE-counted funds with no public footprint. The fix is IESE partnership, not more web research. Pitch: free public resource, attribution, data-sharing both ways.
- Second-best lever: the **investor portfolio pages** (Relay, Istria, Moonbase, Cerralvo, Ambit) refresh continuously — re-scrape quarterly.
- Stale-status badges (Searching + vintage ≤2022) tell you exactly which entries to re-verify first.
- LinkedIn-restricted fields (education, profile URLs) are best filled with a browser-agent pass — 94/148 education fields and 102/148 LinkedIn fields remain open.

## Release notes

**2026-09 (12 Sept 2026)** — Data refresh + dashboard upgrade.
- +14 entries → 162: Semita Capital launch (Spain); Super's Diana / Rigi Capital Partners (Aurica-led, with ICF, Moonbase, Ítaca); four Novastone Capital Advisors operator-led buyouts — Almma/Foo Seng→Apheon exit (France), Savaria Ipartechnika (**Hungary — first entry**), Formeds→Enterprise Investors exit (Poland), Paul Mathew Transport (UK); eight 2026 Spanish acquisitions recorded by target name only (searcher not yet public, low confidence, flagged for dedupe against existing "searching" funds).
- Dashboard: **Download menu** (CSV of current view or full census, Excel workbook, JSON), **shareable URLs** (filters + selected fund encoded in the link hash), **"New this release"** toggle and chips.
- Context: Stanford's July-2026 study identified 190 new international SFs launched 2024–25; Searchfunder's Aug-2026 analysis counts 56+ acquisitions worldwide in 2026 to date (Europe 32). No 2026 IESE international study yet.
- Known gaps to capture next: unnamed 2026 deals in Belgium, Denmark, Luxembourg; Italy's 8 early-2026 launches; 2026 APAC deals (Australia, India, Japan).

## Attribution & license

Kellogg Zell Fellows Give-Back Initiative. Data compiled from public sources: IESE International Search Fund Studies, Stanford GSB Search Fund Studies, Search Funds News, investor portfolio pages, PitchBook/Crunchbase summaries, press, and podcasts. Free to use with attribution. If you republish, link back and preserve the confidence ratings — they are part of the data.
