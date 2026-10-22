"""
Health evaluation for scraper runs.

Websites change, and the most common way a scraper breaks is silently: the
selectors stop matching, `fetch_events()` returns an empty list, and nothing
raises. Left unchecked that is worse than a crash, because orphan cleanup
treats "scraped nothing" as "every stored event is gone from the site" and
deletes the venue's events.

This module inspects a run before anything destructive happens and classifies
it as healthy, suspicious, or failed.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Set


STATUS_HEALTHY = "healthy"
STATUS_SUSPICIOUS = "suspicious"
STATUS_FAILED = "failed"

DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TIME_PATTERN = re.compile(r'^\d{2}:\d{2}$')

# A run may not delete more than this share of a scraper's stored events...
MAX_DELETE_RATIO = 0.5
# ...but only once there are enough stored events for the ratio to mean
# something. Small venues (Z10 currently has 3 upcoming) are covered by the
# "scraped nothing at all" rule instead.
MIN_BASELINE_FOR_RATIO = 5

# Dates outside this window indicate a parsing failure rather than real data.
# Past events are legitimate (AKK's chronicle page lists them), so the past
# bound is generous.
MAX_PAST_YEARS = 2
MAX_FUTURE_YEARS = 3

# If this many events all land on one date, a date parse has probably collapsed.
IDENTICAL_DATE_THRESHOLD = 5

# Skipping cleanup leaves stale rows behind, which inflates the baseline the
# next run is judged against - so a genuine large change (venue overhauls its
# programme, event URLs change) would stay flagged forever and the stale rows
# would never be removed. After this many consecutive flagged runs that still
# return valid, non-empty data, believe the scraper and let cleanup proceed.
# The "scraped nothing at all" rule deliberately never yields this way.
ACCEPT_CHANGE_AFTER_RUNS = 3


@dataclass
class RunVerdict:
    """The outcome of judging a single scraper run."""

    status: str
    reasons: List[str] = field(default_factory=list)
    safe_to_store: bool = True
    safe_to_delete_orphans: bool = True

    @property
    def is_healthy(self) -> bool:
        return self.status == STATUS_HEALTHY

    def summary(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


def validate_events(event_dicts: List[Dict[str, Any]], today: datetime = None) -> List[str]:
    """Check scraped events for signs of a broken parse.

    These are deliberately generic: they catch garbage without needing
    per-scraper tuning, and stay quiet on legitimate data.
    """
    problems = []
    if not event_dicts:
        return problems

    today = today or datetime.now()

    missing_names = sum(1 for e in event_dicts if not (e.get('event_name') or '').strip())
    if missing_names:
        problems.append(f"{missing_names} event(s) have an empty name")

    missing_links = sum(1 for e in event_dicts if not (e.get('link') or '').strip())
    if missing_links:
        problems.append(f"{missing_links} event(s) have an empty link")

    malformed_dates, out_of_range = 0, 0
    for event in event_dicts:
        raw_date = event.get('event_date') or ''
        if not DATE_PATTERN.match(raw_date):
            malformed_dates += 1
            continue
        try:
            parsed = datetime.strptime(raw_date, '%Y-%m-%d')
        except ValueError:
            malformed_dates += 1
            continue
        age_years = (today - parsed).days / 365.25
        if age_years > MAX_PAST_YEARS or age_years < -MAX_FUTURE_YEARS:
            out_of_range += 1

    if malformed_dates:
        problems.append(f"{malformed_dates} event(s) have an unparseable date")
    if out_of_range:
        problems.append(
            f"{out_of_range} event(s) have a date outside "
            f"-{MAX_PAST_YEARS}/+{MAX_FUTURE_YEARS} years"
        )

    malformed_times = sum(
        1 for e in event_dicts
        if e.get('event_time') and not TIME_PATTERN.match(e['event_time'])
    )
    if malformed_times:
        problems.append(f"{malformed_times} event(s) have a malformed time")

    distinct_dates = {e.get('event_date') for e in event_dicts}
    if len(event_dicts) >= IDENTICAL_DATE_THRESHOLD and len(distinct_dates) == 1:
        problems.append(
            f"all {len(event_dicts)} events share one date "
            f"({next(iter(distinct_dates))}) - date parsing likely broken"
        )

    return problems


def evaluate_run(
    event_dicts: List[Dict[str, Any]],
    existing_ids: Set[str],
    consecutive_failures: int = 0,
) -> RunVerdict:
    """Judge a scraper run before storing or deleting anything.

    Args:
        event_dicts: events just scraped, each with an 'id' key.
        existing_ids: IDs already stored in the database for this scraper.
        consecutive_failures: how many runs in a row have already been flagged,
            used to eventually accept a genuine large change instead of
            deadlocking on it.
    """
    problems = validate_events(event_dicts)
    if problems:
        # The data itself looks wrong, so don't let it near the database.
        return RunVerdict(
            status=STATUS_FAILED,
            reasons=problems,
            safe_to_store=False,
            safe_to_delete_orphans=False,
        )

    # Rule A: scraped nothing while the database holds events for this venue.
    # Applies at any size, which is what protects the small venues.
    if not event_dicts and existing_ids:
        return RunVerdict(
            status=STATUS_SUSPICIOUS,
            reasons=[
                f"scraped 0 events but {len(existing_ids)} are stored - "
                f"refusing to delete them"
            ],
            safe_to_store=True,
            safe_to_delete_orphans=False,
        )

    # Rule B: this run would wipe out most of what is stored.
    valid_ids = {e['id'] for e in event_dicts}
    would_delete = existing_ids - valid_ids
    if len(existing_ids) >= MIN_BASELINE_FOR_RATIO and would_delete:
        ratio = len(would_delete) / len(existing_ids)
        if ratio > MAX_DELETE_RATIO:
            if consecutive_failures >= ACCEPT_CHANGE_AFTER_RUNS:
                # It has kept returning valid data this whole time, so this is
                # a real change rather than a break. Accept it, otherwise the
                # skipped rows pile up and the scraper never recovers.
                return RunVerdict(
                    status=STATUS_HEALTHY,
                    reasons=[
                        f"accepting removal of {len(would_delete)} of "
                        f"{len(existing_ids)} events after "
                        f"{consecutive_failures} flagged runs"
                    ],
                )
            return RunVerdict(
                status=STATUS_SUSPICIOUS,
                reasons=[
                    f"run would delete {len(would_delete)} of {len(existing_ids)} "
                    f"stored events ({ratio:.0%}) - keeping them"
                ],
                safe_to_store=True,
                safe_to_delete_orphans=False,
            )

    return RunVerdict(status=STATUS_HEALTHY)
