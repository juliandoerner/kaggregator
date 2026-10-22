"""
Scraper Service Main Entry Point - Minimal implementation.

Runs all enabled scrapers on a schedule and stores events in the database.
"""

import logging
import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.blocking import BlockingScheduler

from ka_events.config import get_config
from ka_events.registry import ScraperRegistry
from ka_events.database import (
    init_db,
    upsert_events,
    update_scraper_status,
    delete_orphaned_events,
    record_scraper_run,
    get_event_ids_for_scraper,
    get_last_successful_run,
    get_scraper_health,
    set_scraper_health,
)
from ka_events.health import evaluate_run, RunVerdict, STATUS_FAILED
from ka_events.logging_config import configure_logging
from ka_events.notifications import EmailNotifier, format_alert, format_recovery


logger = logging.getLogger(__name__)


# Which scrapers run, and how venues are labelled, comes from config.yaml.
# Deployment values still come from the environment.
CONFIG = get_config()
SCRAPE_INTERVAL = CONFIG.scrape_interval
DATABASE_PATH = CONFIG.database_path

# How many consecutive bad runs before mailing, so a transient site outage
# doesn't page you. At the default 6h interval, 2 means roughly half a day.
ALERT_AFTER_FAILURES = int(os.environ.get("ALERT_AFTER_FAILURES", 2))

# Venues are fetched in parallel (different hosts); each scraper still paces
# its own requests to a single host.
SCRAPER_CONCURRENCY = int(os.environ.get("SCRAPER_CONCURRENCY", 4))


def _fetch_one(registry, scraper_name):
    """Fetch a single scraper's events. Runs in a worker thread.

    Returns (name, events, error) so the caller can handle failures on the main
    thread, where all the database and alerting logic lives.
    """
    scraper = None
    try:
        logger.info("[%s] fetching", scraper_name)
        scraper = registry.get_scraper(scraper_name)
        return scraper_name, scraper.fetch_events(), None
    except Exception as exc:
        return scraper_name, None, exc
    finally:
        if scraper is not None:
            scraper.close()


def run_scrapers():
    """Run all enabled scrapers and store results.

    Fetching happens concurrently, storing happens sequentially on this thread.
    That split is deliberate: the work is I/O-bound so concurrency helps, but
    SQLite wants a single writer and the health/alerting logic reads and writes
    state per scraper, which is far simpler to reason about un-parallelised.

    Concurrency is *across* venues, never within one. Each scraper still paces
    its own requests (Stadtmitte sleeps between its twelve month pages), so no
    single site sees a burst - we just talk to different sites at once.
    """
    enabled = get_config().enabled_scrapers
    logger.info("Starting scraper run (%d scrapers, %d workers)",
                len(enabled), SCRAPER_CONCURRENCY)

    registry = ScraperRegistry()
    notifier = EmailNotifier()

    if not notifier.is_configured:
        logger.warning("SMTP not configured - health problems will only be logged")

    results = []
    with ThreadPoolExecutor(max_workers=SCRAPER_CONCURRENCY) as pool:
        futures = [pool.submit(_fetch_one, registry, name) for name in enabled]
        for future in futures:
            results.append(future.result())

    for scraper_name, events, error in results:
        try:
            if error is not None:
                raise error

            # Convert events to dicts with IDs and scraper source. The scraper
            # name namespaces source-provided IDs, which are only unique per site.
            event_dicts = []
            valid_ids = set()
            for event in events:
                event_dict = event.to_dict()
                event_dict['id'] = event.generate_id(scraper_name)
                event_dict['scraper_source'] = scraper_name
                event_dicts.append(event_dict)
                valid_ids.add(event_dict['id'])

            # Judge the run *before* touching the database. A silently broken
            # scraper returns an empty list without raising, and orphan cleanup
            # would read that as "every stored event is gone from the site".
            existing_ids = get_event_ids_for_scraper(scraper_name, DATABASE_PATH)
            verdict = evaluate_run(
                event_dicts,
                existing_ids,
                get_scraper_health(scraper_name, DATABASE_PATH)['consecutive_failures'],
            )

            count = 0
            if verdict.safe_to_store:
                count = upsert_events(event_dicts, DATABASE_PATH)

            if verdict.safe_to_delete_orphans:
                deleted = delete_orphaned_events(scraper_name, valid_ids, DATABASE_PATH)
                if deleted > 0:
                    logger.info("[%s] removed %d orphaned event(s)", scraper_name, deleted)
            elif existing_ids:
                logger.warning("[%s] skipped orphan cleanup: %s", scraper_name, verdict.summary())

            if verdict.is_healthy:
                logger.info("[%s] found %d events", scraper_name, count)
            else:
                logger.warning("[%s] %s: %s", scraper_name, verdict.status.upper(), verdict.summary())

            update_scraper_status(
                scraper_name,
                "success" if verdict.is_healthy else verdict.status,
                count,
                DATABASE_PATH,
            )
            record_scraper_run(
                scraper_name, verdict.status, count,
                verdict.summary(), DATABASE_PATH,
            )
            _update_health(scraper_name, verdict, count, len(existing_ids), notifier)

        except Exception as e:
            logger.exception("[%s] failed: %s", scraper_name, e)
            update_scraper_status(scraper_name, f"error: {e}", 0, DATABASE_PATH)
            record_scraper_run(
                scraper_name, STATUS_FAILED, 0,
                f"{type(e).__name__}: {e}", DATABASE_PATH,
            )
            stored = len(get_event_ids_for_scraper(scraper_name, DATABASE_PATH))
            _update_health(
                scraper_name,
                RunVerdict(
                    status=STATUS_FAILED,
                    reasons=[f"{type(e).__name__}: {e}"],
                    safe_to_store=False,
                    safe_to_delete_orphans=False,
                ),
                0, stored, notifier,
            )

    logger.info("Scraper run completed")


def _update_health(scraper_name, verdict, events_found, stored_events, notifier):
    """Track consecutive failures and mail on health *transitions*.

    Mailing on transitions rather than on every bad run means a scraper that
    stays broken sends one alert, not one every SCRAPE_INTERVAL.
    """
    health = get_scraper_health(scraper_name, DATABASE_PATH)
    failures = health['consecutive_failures']
    alerted = health['alerted']

    if verdict.is_healthy:
        if alerted:
            subject, body = format_recovery(scraper_name, events_found)
            notifier.send(subject, body)
        set_scraper_health(scraper_name, 0, 0, DATABASE_PATH)
        return

    failures += 1
    if failures >= ALERT_AFTER_FAILURES and not alerted:
        subject, body = format_alert(
            scraper_name=scraper_name,
            status=verdict.status,
            reasons=verdict.reasons,
            consecutive_failures=failures,
            events_found=events_found,
            stored_events=stored_events,
            last_success=get_last_successful_run(scraper_name, DATABASE_PATH),
        )
        if notifier.send(subject, body):
            alerted = 1
    elif failures < ALERT_AFTER_FAILURES:
        logger.info("[%s] failure %d/%d - not alerting yet",
                    scraper_name, failures, ALERT_AFTER_FAILURES)

    set_scraper_health(scraper_name, failures, alerted, DATABASE_PATH)


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutting down scraper service")
    sys.exit(0)


def main():
    """Main entry point."""
    configure_logging()

    # Fail loudly at startup if config.yaml names a scraper that doesn't exist,
    # rather than warning about it once per run forever.
    config = get_config()
    config.validate(ScraperRegistry().available_scrapers)
    logger.info("Enabled scrapers: %s", ", ".join(config.enabled_scrapers))

    logger.info("Initializing database at %s", DATABASE_PATH)
    init_db(DATABASE_PATH)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run once on startup so a fresh installation has data immediately
    run_scrapers()

    scheduler = BlockingScheduler()
    scheduler.add_job(run_scrapers, 'interval', seconds=SCRAPE_INTERVAL)

    logger.info(
        "Scheduled scrapers every %d seconds (%.1f hours); Ctrl+C to stop",
        SCRAPE_INTERVAL, SCRAPE_INTERVAL / 3600,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
