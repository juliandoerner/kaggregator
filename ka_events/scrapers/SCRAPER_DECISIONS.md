# Scraper Implementation Decisions

This document describes the design decisions and implementation details for each venue scraper in the KA Events project.

---

## General Architecture

### Auto-Discovery Pattern
Scrapers are auto-discovered from the `scrapers/` subdirectory by the `ScraperRegistry`. Any Python file (not starting with `_`) that contains a class inheriting from `BaseScraper` with a `name` attribute is automatically registered.

### Common Interface
All scrapers implement the `BaseScraper` interface:
- `name`: Unique identifier for the scraper
- `url`: Target URL to scrape
- `fetch_events() -> list[Event]`: Main method returning standardized `Event` objects

### Event Model
```python
@dataclass
class Event:
    event_name: str
    event_date: str      # YYYY-MM-DD format
    event_time: str      # HH:MM format (optional)
    venue: str           # Venue name
    link: str            # Event URL
    
    def generate_id(self) -> str:
        """Generate unique ID from event data."""
        ...
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        ...
```

Events are stored with a generated ID based on name slug + date for deduplication. The `scraper_source` field is added automatically when storing to the database.

---

## Individual Scrapers

### AKK Liveschlonz (`akk.py`)

**Target:** [https://www.akk.org/chronologie.php](https://www.akk.org/chronologie.php)

**Venue:** AKK (Altes Stadion Karlsruhe) - Student-run venue known for "Liveschlonz" concerts.

#### Decisions Made:

1. **Table-Based Parsing**: The AKK website uses HTML tables to list events. We parse `<tr class="liveschlonz">` rows specifically to target only concert events.

2. **Datetime Attribute**: Event times are stored in a `datetime` attribute on `<time>` elements in ISO format (`2026-04-23T18:00`), making parsing straightforward.

3. **Venue Normalization**: The 4th column contains venue information. We normalize "Altes Stadion" to "AKK - Altes Stadion" for consistency.

4. **Name Cleaning**: Strip the "Liveschlonz:" prefix from event names for cleaner display.

5. **No Category Filtering Needed**: The chronologie page only lists "Liveschlonz" events by design, so no additional filtering is required.

---

### Z10 (`z10.py`)

**Target:** [https://z10.info/](https://z10.info/)

**Venue:** Studentenzentrum Zähringerstraße 10 e.V. - Student center with diverse events.

#### Decisions Made:

1. **JSON-LD Structured Data**: Z10 embeds Schema.org Event data in `<script type="application/ld+json">` tags. This is more reliable than HTML parsing and provides rich metadata.

2. **Category-Based Filtering**: Z10 hosts many non-music events (chess club, workshops, info sessions). We filter by the `datecategory` span:
   - **Keep:** Konzert, Party, Theater, Kabarett, Lesung
   - **Skip:** Krümel (chess), Info-Veranstaltung, Kurs, Vortrag, Quiz, etc.

3. **Historical Analysis**: We analyzed archive pages (2023-2026) to understand all possible categories:
   - Konzerte and Parties are the primary music events
   - "Krümel" (chess) is surprisingly the most frequent category
   - Theater/Kabarett/Lesung are occasional cultural events worth including

4. **Custom Datetime Parsing**: Z10 uses a non-standard format: `2026-07-17CEST22:00`. We handle this with regex before falling back to ISO parsing.

5. **Deterministic ID Generation**: For deduplication, we generate IDs from event name slugs + date: `z10_the-jericho-racks-uk-haloquadratum-wasabi-ka_20260912`

---

### Staatstheater Karlsruhe (`staatstheater.py`)

**Target:** [https://www.staatstheater-karlsruhe.de/spielplan/](https://www.staatstheater-karlsruhe.de/spielplan/)

**Venue:** Badisches Staatstheater Karlsruhe - Hermann-Levi-Platz 1, 76137 Karlsruhe

#### Decisions Made:

1. **Month-Based Navigation**: The site organizes events by month in a left sidebar navigation. Each month has its own page (e.g., `/spielplan/september/`, `/spielplan/juli-26/`). We scrape the main page AND all linked month pages to get the full season schedule.

2. **Event Structure**: Events are displayed in `div.row-divider` elements with three columns:
   - Column 1: Time and category (Oper, Ballett, Konzert, Schauspiel, etc.)
   - Column 2: Event title and description
   - Column 3: Venue and ticket information

3. **Date Parsing**: German date format in headers like "Montag, 6.7." requires custom parsing. We handle year boundaries (if month < current month, assume next year).

4. **Event Name Prefix**: We add `[Staatstheater]` prefix to all event names for clear attribution (similar to how AKK uses "Liveschlonz:" prefix).

5. **Deduplication**: The same event may appear on both the main page and month sub-pages. We deduplicate using a composite key of (event_name, event_date, event_time).

6. **Category Filtering**: We exclude certain categories that don't fit our music/events focus:
   - **Keep:** Oper, Ballett, Konzert, Schauspiel, Junges Staatstheater, Digitaltheater
   - **Exclude:** Kunst + Vermittlung (art/education), Extras (special events)

6. **Multiple Venues**: Events can be at various venues: Großes Haus, Kleines Haus, Neues Entrée, Insel, or external locations like Electric Eel or Naturkunde Museum.

---

### Substage Karlsruhe (`substage.py`)

**Target:** [https://substage.de/programm/](https://substage.de/programm/)

**Venue:** Substage Karlsruhe e.V. - Karlstraße 28, 76137 Karlsruhe

#### Decisions Made:

1. **AJAX-Based Data Loading**: The Substage website uses JavaScript to load events dynamically via an AJAX POST request to `includes/programm_uebersicht_load.php`. We replicate this request directly instead of rendering JavaScript.

2. **Category Filtering**: The site provides filter options for event types (Veranstaltungsart):
   - **Keep:** Live (concerts, bands)
   - **Skip:** Party (club nights), Gastronomie (wine tastings, food events)

3. **German Date Format**: Dates are in DD.MM.YY format (e.g., "11.07.26"). We parse this with regex and convert to YYYY-MM-DD.

4. **Location Handling**: Events can be at different locations within Substage:
   - Halle (main hall for big concerts)
   - Minestrone (cafe area)
   - Hof (courtyard)
   
   We add "Substage - " prefix to all venues for consistency (e.g., "Substage - Halle").

5. **Event Structure**: Each event is in a `div.mod_kalender_element` with:
   - Date column: Day name, date (DD.MM.YY), start time, doors open time, location
   - Title column: Event title with link to detail page
   - Optional: Sold out indicators, ticket purchase links

---

### Dummy Scraper (`dummy.py`)

**Purpose:** Testing and development.

#### Decisions Made:

1. **Static Test Data**: Returns predictable, hardcoded events for consistent testing.

2. **Disabled by Default**: Not included in production `config.yaml` to avoid polluting the database with fake events.

3. **Use Cases:**
   - Unit testing the scraper pipeline
   - Integration testing database operations
   - Development/testing without hitting external APIs

---

## Implemented Scrapers

| Scraper | Venue | Status | Notes |
|---------|-------|--------|-------|
| `akk.py` | AKK Liveschlonz | ✅ Active | Table-based parsing |
| `kohi.py` | KOHI Kulturraum | ✅ Active | Article-based with JSON-LD |
| `staatstheater.py` | Staatstheater Karlsruhe | ✅ Active | Month navigation crawling |
| `substage.py` | Substage Karlsruhe | ✅ Active | AJAX API replication |
| `tollhaus.py` | Tollhaus Karlsruhe | ✅ Active | Main site link scraping |
| `z10.py` | Z10 Studentenzentrum | ✅ Active | JSON-LD structured data |
| `pacht.py` | P8 (p-acht.org) | ✅ Active | Next.js `__NEXT_DATA__` payload |
| `jubez.py` | jubez | ✅ Active | Nuxt `__NUXT_DATA__` payload (devalue format) |
| `stadtmitte.py` | Die Stadtmitte | ✅ Active | Month pages via self-computed `?timestamp=` |
| `dummy.py` | Test/Dummy | ✅ Available | Development/testing only |

---

### Tollhaus (`tollhaus.py`)

**Target:** https://www.tollhaus.de/

**Venue:** Kulturzentrum Tollhaus Karlsruhe - Rintheimer Straße 22b, 76131 Karlsruhe

#### Implementation Details:

1. **Two-Site Architecture**:
   - Main site (`www.tollhaus.de`): Marketing site with event listings
   - Ticket site (`tickets.tollhaus.de`): SPA booking system (not directly scrapable)

2. **Approach Used**: Main Site Scraping (Option B from original plan)
   - Scrape `https://www.tollhaus.de/` homepage
   - Extract all links matching `/catalog/tickets/` pattern
   - Parse event name and date from link text

3. **Link Text Format**: `"DD.MM.YY // EVENT NAME"`
   - Example: `"07.07.26 // JAN GARBAREK GROUP"`
   - Regex parsing extracts date and name separately

4. **Fallback Date Extraction**: If not in link text, try URL pattern:
   - URL format: `/catalog/tickets/{id}-tickets-{slug}-{date}`
   - Regex: `am-(\d{2})-(\d{2})-(\d{4})`

5. **Category Filtering**: Implemented via link text analysis
   - **Keep:** Konzert, Kabarett, Comedy, Theater, Party
   - Filter happens implicitly by only following ticket links

6. **Venue Handling**: 
   - Default: "Tollhaus"
   - Special: "Tollhaus @ Zeltival" for outdoor festival events

7. **Name Cleaning**:
   - Remove "AUSVERKAUFT" (sold out) suffix
   - Strip whitespace

---

### P8 / p-acht.org (`pacht.py`)

**Target:** [https://p-acht.org/](https://p-acht.org/)

**Venue:** P8 - self-managed DIY cultural space in Karlsruhe (no street address published on the site).

#### Decisions Made:

1. **Next.js `__NEXT_DATA__` Payload**: The site is a Next.js SPA. Rather than rendering JavaScript or hitting an internal API, we fetch the plain homepage HTML and extract the `<script id="__NEXT_DATA__">` JSON blob that Next.js embeds for server-side rendering. This is more reliable than HTML/CSS parsing since it's the exact data the page itself was built from.

2. **Homepage Already Has the Full Listing**: `props.pageProps.eventListData` on the homepage contains *all* upcoming events (observed spanning ~8 months ahead, e.g. July 2026 through March 2027), not just the current month, despite the site also exposing a month-by-month calendar (`calLinks.nextMonthLink`, etc.). No month-crawling or pagination is needed — a single request to `/` is sufficient for the full valid-ID set required by orphan cleanup.

3. **Structure**: `eventListData` is a dict keyed by location (currently only one key, `"P8"`, the venue's own name); each entry is a list of `{name, id, slug, dateFrom, dateTo, location: {name}}` objects. We iterate over all keys defensively in case the venue is ever split into sub-locations in their data model, though in practice there's just the one.

4. **UTC → Local Time Conversion**: `dateFrom` is UTC ISO8601 (e.g. `"2026-07-31T18:00:00.000Z"`). We convert to Europe/Berlin local time with `pytz` (already a transitive dependency via APScheduler, now declared directly) to get the correct wall-clock date/time, correctly handling the CET/CEST DST boundary.

5. **No Category Filtering**: The event objects expose no category/type field (unlike Z10 or Substage), even though the venue's "About us" page describes hosting concerts, readings, exhibitions, theater, dance, workshops, and parties. Determining category would require fetching and parsing each event's detail page, which isn't justified by the data available — so, like AKK, all listed events are included as-is.

6. **Link**: Built directly from the slug as `https://p-acht.org/events/{slug}` — the site's own event detail page, consistent with how AKK and Z10 link back to source pages rather than external ticket vendors.

---

### jubez (`jubez.py`)

**Target:** [https://jubez.de/#programm](https://jubez.de/#programm)

**Venue:** jubez - Kunst- und Kulturzentrum am Kronenplatz, Kronenplatz 1, 76133 Karlsruhe.

#### Decisions Made:

1. **Nuxt `__NUXT_DATA__` Payload**: Like P8, the site is a JS SPA (Nuxt 3 this time, backed by a headless WordPress/WPGraphQL API at `headless.jubez.de`). We fetch the plain homepage HTML and parse the `<script type="application/json" id="__NUXT_DATA__">` payload it embeds for SSR hydration, rather than calling the GraphQL API or rendering JavaScript.

2. **Devalue-Style Flat Array Format**: Unlike Next.js's plain nested JSON, Nuxt serializes this payload as a flat array where *every* value — object, array, or primitive — gets its own slot, and any reference to it from a parent structure is just that slot's integer index (this is what lets it dedupe repeated values and represent cyclic/shared references). `_extract_nuxt_payload()` implements a small generic resolver that recursively dereferences these indices from the root (slot 0) into an ordinary nested Python structure. This is a reusable technique, not p-acht-specific — worth remembering for any other Nuxt 3 site.

3. **robots.txt Consideration**: `headless.jubez.de/robots.txt` disallows all crawling (`Disallow: /`), while `jubez.de/robots.txt` allows everything. We deliberately avoid ever calling the GraphQL API directly (even though the exact query — `EventsQuery`, filtering `status: upcoming` — was recoverable from the shipped JS bundles) and only ever fetch `jubez.de/` itself, parsing the same SSR payload the site already serves to any visitor's browser. This also happens to be *sufficient*: the homepage's embedded events connection reports `pageInfo.hasNextPage: false`, confirming it already contains the complete upcoming events list (verified against the unfiltered GraphQL result directly during analysis, before settling on this approach) — no pagination gap to worry about.

4. **Generic Key Lookup**: The events connection lives under a randomly-hashed per-build key (e.g. `wGfWKxsWSd`) inside the payload's `data` object, not a stable name — `_find_events_connection()` searches by shape (`{events: {edges: [...]}}`) instead of hardcoding that key, so it survives site rebuilds.

5. **Cancelled Events**: The `status: upcoming` filter is date-based only — a cancelled event happening in the future still comes back with `eventSettings.cancelled` set (observed value: `"cancelled"`), so it's filtered out explicitly in `_parse_event()`.

6. **No Category Filtering**: As with P8, the GraphQL `Event` type exposes no category/type field, despite the venue's own description covering concerts, readings, and workshops. All non-cancelled upcoming events are included as-is.

7. **Venue/Sub-location**: `eventSettings.location.title` gives sub-room names like "jubez Großer Saal" or "jubez Cafe und kleiner Saal"; falls back to the site's own name "jubez" when null (mirrors KOHI's `@ sublocation` pattern — grouped back together in the web UI's location filter via `scraper_source`, not `venue` text).

---

### Die Stadtmitte (`stadtmitte.py`)

**Target:** [https://die-stadtmitte.de/programm.php](https://die-stadtmitte.de/programm.php)

**Venue:** Die Stadtmitte - club and event venue, Baumeisterstraße 3, 76137 Karlsruhe.

#### Decisions Made:

1. **Server-Rendered Month Pages**: `programm.php` renders a calendar plus an `.events-overview` list for whichever month contains the `?timestamp=` query parameter. Each `.overview-event` block carries the date, time, title *and* the full description — the detail panel is only hidden with CSS (`displaynone`), not loaded on demand. So the whole programme comes from ordinary page fetches; the site's AJAX endpoint `/post-data.php` is never touched (it is also `Disallow`ed in `robots.txt`, unlike `programm.php` which is explicitly allowed).

2. **We Compute Month Timestamps Ourselves — Do Not Follow "Next Month"**: The site's own next-month arrow just adds 31 days to the current timestamp. Whenever that overshoots the following month, a month is skipped entirely: from `2026-08-31` it links to `2026-10-01`, so **September disappears from the site's own navigation** (its 3 events are unreachable by clicking through). `_month_timestamps()` therefore generates one timestamp per calendar month itself, using **mid-month noon** — a point safely inside every month regardless of month length or DST shifts. Verified: crawling by navigation yields 24 events, computing months yields 36.

3. **Fixed 12-Month Horizon**: `MONTHS_AHEAD = 12`, starting from the current month. The venue publishes roughly 5 months out, so this is generous headroom. A fixed horizon is deliberate over an "stop at the first empty month" heuristic, because September 2026 is exactly the case that would break it — an empty or sparse month in the middle of a published programme. Under this project's orphan-cleanup model a partial listing is actively destructive (events not returned get deleted), so completeness is worth the extra requests. Requests are spaced by 0.5s.

4. **Date/Time Formats**: dates render as `DD/MM.YYYY` (e.g. `01/08.2026`, note the slash *and* the dot) and times as `Sa - 21:00 Uhr`, both parsed by regex.

5. **Per-Event Links and the Same-Day Collision**: Events have no individual pages — they expand inline via JavaScript, so every anchor is `href='#'`. Each does carry a stable unique anchor id (`event_2113`), which we append as a fragment: `programm.php#event_2113`. This matters because `Event.generate_id()` hashes `date|venue|link`: the venue is constant and two events on one day do occur (2026-08-12 has both "Heavy//Hitter" and "Karls Afterwork"), so without the per-event fragment they would hash identically and one would silently overwrite the other. The ids are also stable between runs, so event IDs don't churn and trigger needless orphan deletion + reinsertion.

6. **No Category Filtering**: `.overview-event` blocks carry no category/type marker (every block has exactly the one class). The programme mixes club nights, tribute acts and live concerts; all are included. A separate `konzerte.php` page lists only the concerts, but `programm.php` is the superset and the requested source.

---

## Deprecated/Removed Scrapers

The following scrapers were initially created for prototyping but are no longer needed:

- `tempel.py` - Kulturzentrum Tempel (venue not in scope)

---

## Best Practices

### General Guidelines:

1. **Respect robots.txt**: Check the target site's robots.txt before scraping
2. **Rate Limiting**: Add appropriate delays between requests if scraping multiple pages
3. **Error Handling**: Always use try/except for network operations
4. **Timeouts**: Set reasonable timeouts (30s default) on HTTP requests
5. **User-Agent**: Use a descriptive User-Agent header to identify your scraper
6. **Idempotency**: Ensure repeated runs produce identical results
7. **Documentation**: Update this file when adding new scrapers
8. **Deterministic IDs**: Generate consistent event IDs from stable attributes (name slug + date)
9. **Link Preference**: Prefer external ticket links over internal detail pages when available

### Event Data Requirements:

| Field | Format | Notes |
|-------|--------|-------|
| `event_name` | String | Clean, trimmed. Remove venue prefixes if redundant |
| `event_date` | YYYY-MM-DD | ISO format required |
| `event_time` | HH:MM | 24-hour format, optional |
| `venue` | String | Include venue prefix for clarity (e.g., "KOHI - ") |
| `link` | Full URL | Prefer ticket purchase URLs, fallback to event detail pages |
| `source` | String | Auto-populated from scraper name |

### Category Filtering Strategy:

When venues host mixed content (not just music/concerts):
1. Analyze all available categories first
2. Document which to keep vs. skip
3. Implement explicit filtering logic
4. Log/filter decisions should be transparent

### Technical Approaches by Site Type:

| Site Type | Approach | Example |
|-----------|----------|---------|
| Static HTML | Parse `<article>` or `<div>` elements | KOHI |
| JSON-LD Structured Data | Parse `<script type="application/ld+json">` | Z10 |
| AJAX/Dynamic | Replicate API calls directly | Substage |
| Month Navigation | Crawl main + sub-pages | Staatstheater |
| Table-Based | Parse `<tr>` rows with class markers | AKK |
| Next.js Embedded Data | Parse `<script id="__NEXT_DATA__">` JSON | P8 (pacht) |
| Nuxt Embedded Data | Parse `<script id="__NUXT_DATA__">` devalue-format JSON | jubez |
| Month Query Parameter | Request `?timestamp=` per self-computed month | Die Stadtmitte |

### Testing:

- Run individual scrapers: `python -c "from scraper_service.scrapers.z10 import Z10Scraper; print(Z10Scraper().fetch_events())"`
- Run test suite: `pytest tests/ -v`
- Test specific categories: `pytest tests/test_registry.py -v`
- Verify category filtering matches intended event types

---

## Technical Reference

### Database Schema

```sql
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    event_date TEXT NOT NULL,
    event_time TEXT,
    event_name TEXT,
    venue TEXT,
    link TEXT,
    scraper_source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE scrapers (
    name TEXT PRIMARY KEY,
    last_run TEXT,
    last_status TEXT,
    events_found INTEGER DEFAULT 0
);
```

### Event ID Generation

Event IDs are generated deterministically from event data to enable deduplication:

```python
def generate_id(self) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', self.event_name.lower()).strip('-')
    date_str = self.event_date.replace('-', '')
    return f"{self.venue}_{slug}_{date_str}"
```

Example: `kohi_the-jericho-racks_20260717`

### Category Filtering by Scraper

| Scraper | Keep Categories | Skip Categories |
|---------|-----------------|-----------------|
| z10 | Konzert, Party, Theater, Kabarett, Lesung | Krümel, Info-Veranstaltung, Kurs, Vortrag, Quiz |
| substage | Live | Party, Gastronomie |
| staatstheater | Oper, Ballett, Konzert, Schauspiel, Junges Staatstheater, Digitaltheater | Kunst + Vermittlung, Extras |
| akk | (all Liveschlonz events) | N/A - already filtered by table class |
| kohi | Konzert, Songslam, Literatur, Theater, Poetry-Slam | Sonstiges, Querfunk, Gattung |
| tollhaus | Konzert, Kabarett, Comedy, Theater, Party | N/A - implicit via ticket links |
| pacht | (all events) | N/A - no category field in source data |
| jubez | (all non-cancelled events) | N/A - no category field; cancelled events excluded |
| stadtmitte | (all events) | N/A - no category field in markup |
