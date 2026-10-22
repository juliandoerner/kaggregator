"""
Tests for scraper health evaluation and alert formatting.
"""

from datetime import datetime, timedelta


from ka_events.health import (
    evaluate_run,
    validate_events,
    STATUS_HEALTHY,
    STATUS_SUSPICIOUS,
    STATUS_FAILED,
)
from ka_events.notifications import EmailNotifier, format_alert, format_recovery


def make_events(count, start_day=1, scraper='kohi', same_date=False):
    """Build well-formed scraped-event dicts."""
    events = []
    for i in range(count):
        day = start_day if same_date else start_day + i
        date = (datetime.now() + timedelta(days=day)).strftime('%Y-%m-%d')
        events.append({
            'id': f'{scraper}-{i}',
            'event_name': f'Concert {i}',
            'event_date': date,
            'event_time': '20:00',
            'venue': 'KOHI',
            'link': f'https://kohi.de/{i}',
            'scraper_source': scraper,
        })
    return events


class TestValidateEvents:
    """Generic checks that catch a broken parse without per-scraper tuning."""

    def test_clean_events_have_no_problems(self):
        assert validate_events(make_events(5)) == []

    def test_empty_list_has_no_problems(self):
        # "Scraped nothing" is handled by evaluate_run, not by validation.
        assert validate_events([]) == []

    def test_flags_empty_names(self):
        events = make_events(3)
        events[0]['event_name'] = '   '
        assert any('empty name' in p for p in validate_events(events))

    def test_flags_empty_links(self):
        events = make_events(3)
        events[1]['link'] = ''
        assert any('empty link' in p for p in validate_events(events))

    def test_flags_unparseable_date(self):
        events = make_events(2)
        events[0]['event_date'] = 'Freitag'
        assert any('unparseable date' in p for p in validate_events(events))

    def test_flags_absurd_date(self):
        events = make_events(2)
        events[0]['event_date'] = '1970-01-01'
        assert any('outside' in p for p in validate_events(events))

    def test_allows_recent_past_dates(self):
        """AKK's chronicle page legitimately returns past events."""
        past = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        events = make_events(3)
        for e in events:
            e['event_date'] = past
        # Past dates are fine; only the all-same-date rule could fire, and
        # that needs 5+ events.
        assert validate_events(events) == []

    def test_flags_malformed_time(self):
        events = make_events(2)
        events[0]['event_time'] = '8 Uhr'
        assert any('malformed time' in p for p in validate_events(events))

    def test_allows_missing_time(self):
        events = make_events(2)
        events[0]['event_time'] = None
        assert validate_events(events) == []

    def test_flags_all_events_on_one_date(self):
        events = make_events(6, same_date=True)
        assert any('share one date' in p for p in validate_events(events))

    def test_few_events_on_one_date_is_allowed(self):
        """Two events on one day is normal (Stadtmitte 2026-08-12)."""
        assert validate_events(make_events(2, same_date=True)) == []


class TestEvaluateRun:
    """The guard that decides whether destructive cleanup may run."""

    def test_healthy_run_allows_cleanup(self):
        events = make_events(10)
        existing = {e['id'] for e in events}

        verdict = evaluate_run(events, existing)

        assert verdict.status == STATUS_HEALTHY
        assert verdict.safe_to_store
        assert verdict.safe_to_delete_orphans

    def test_zero_events_with_stored_data_is_suspicious(self):
        """The silent-break case: selectors stop matching, nothing raises."""
        verdict = evaluate_run([], {'a', 'b', 'c'})

        assert verdict.status == STATUS_SUSPICIOUS
        assert not verdict.safe_to_delete_orphans
        assert 'refusing to delete' in verdict.summary()

    def test_zero_events_protects_small_venues(self):
        """Below the ratio baseline, so only the zero-rule can save it."""
        verdict = evaluate_run([], {'a', 'b', 'c'})
        assert not verdict.safe_to_delete_orphans

    def test_zero_events_on_empty_db_is_healthy(self):
        """First run, or a venue with genuinely nothing scheduled."""
        verdict = evaluate_run([], set())

        assert verdict.status == STATUS_HEALTHY
        assert verdict.safe_to_delete_orphans

    def test_drastic_drop_is_suspicious(self):
        events = make_events(2)
        existing = {f'kohi-{i}' for i in range(20)}

        verdict = evaluate_run(events, existing)

        assert verdict.status == STATUS_SUSPICIOUS
        assert not verdict.safe_to_delete_orphans
        assert verdict.safe_to_store, "the events we did get are still stored"

    def test_normal_churn_is_healthy(self):
        """A few events passing between runs must not trip the guard."""
        events = make_events(10)
        existing = {e['id'] for e in events} | {'kohi-old-1', 'kohi-old-2'}

        verdict = evaluate_run(events, existing)

        assert verdict.status == STATUS_HEALTHY
        assert verdict.safe_to_delete_orphans

    def test_small_stored_set_not_judged_by_ratio(self):
        """Below MIN_BASELINE_FOR_RATIO the ratio rule is too noisy to apply."""
        events = make_events(1)
        existing = {'kohi-0', 'kohi-x', 'kohi-y'}

        verdict = evaluate_run(events, existing)

        assert verdict.status == STATUS_HEALTHY

    def test_large_change_is_accepted_after_repeated_flagging(self):
        """Otherwise the skipped rows inflate the baseline and the scraper
        stays flagged forever, never cleaning them up."""
        events = make_events(2)
        existing = {f'kohi-{i}' for i in range(20)}

        stuck = evaluate_run(events, existing, consecutive_failures=3)

        assert stuck.status == STATUS_HEALTHY
        assert stuck.safe_to_delete_orphans
        assert 'accepting removal' in stuck.summary()

    def test_zero_events_never_yields_however_long_it_persists(self):
        """A silent break must not eventually delete everything."""
        verdict = evaluate_run([], {'a', 'b', 'c'}, consecutive_failures=99)

        assert verdict.status == STATUS_SUSPICIOUS
        assert not verdict.safe_to_delete_orphans

    def test_invalid_data_never_yields_however_long_it_persists(self):
        events = make_events(3)
        events[0]['event_date'] = 'not-a-date'

        verdict = evaluate_run(events, set(), consecutive_failures=99)

        assert verdict.status == STATUS_FAILED
        assert not verdict.safe_to_store

    def test_invalid_data_blocks_storage_entirely(self):
        events = make_events(3)
        events[0]['event_date'] = 'not-a-date'

        verdict = evaluate_run(events, set())

        assert verdict.status == STATUS_FAILED
        assert not verdict.safe_to_store
        assert not verdict.safe_to_delete_orphans


class TestEmailNotifier:
    """The notifier must be inert unless explicitly configured."""

    def test_unconfigured_notifier_is_not_configured(self):
        notifier = EmailNotifier(host='', recipient='', sender='')
        assert not notifier.is_configured

    def test_unconfigured_send_returns_false_and_does_not_raise(self):
        notifier = EmailNotifier(host='', recipient='', sender='')
        assert notifier.send('subject', 'body') is False

    def test_configured_when_host_and_addresses_present(self):
        notifier = EmailNotifier(
            host='smtp.example.com', recipient='me@example.com',
            sender='bot@example.com',
        )
        assert notifier.is_configured

    def test_send_failure_is_swallowed(self):
        """A broken mail server must never take down a scrape run."""
        notifier = EmailNotifier(
            host='127.0.0.1', port=9, recipient='me@example.com',
            sender='bot@example.com', use_tls=False,
        )
        assert notifier.send('subject', 'body') is False


class TestAlertFormatting:
    def test_alert_mentions_scraper_and_reasons(self):
        subject, body = format_alert(
            scraper_name='kohi',
            status=STATUS_SUSPICIOUS,
            reasons=['scraped 0 events but 17 are stored - refusing to delete them'],
            consecutive_failures=2,
            events_found=0,
            stored_events=17,
            last_success={'run_at': '2026-07-30T06:00:00', 'events_found': 17},
        )

        assert 'kohi' in subject
        assert STATUS_SUSPICIOUS in subject
        assert 'refusing to delete' in body
        assert '2026-07-30T06:00:00' in body
        assert 'scrapers/kohi.py' in body

    def test_alert_without_previous_success(self):
        _, body = format_alert(
            scraper_name='z10', status=STATUS_FAILED, reasons=['boom'],
            consecutive_failures=3, events_found=0, stored_events=0,
            last_success=None,
        )
        assert 'none on record' in body

    def test_recovery_mentions_count(self):
        subject, body = format_recovery('kohi', 17)
        assert 'recovered' in subject
        assert '17 events' in body
