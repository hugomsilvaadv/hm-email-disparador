import os
import time
from datetime import datetime, timezone

from app import AjtSendLog, app
from ajt_trt3 import TRT3_BATCH_1, TRT3_INDIVIDUAL_UNITS, send_trt3_individual_email


def sent_today_count():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return AjtSendLog.query.filter(
        AjtSendLog.sent_at >= start,
        AjtSendLog.result == "sent",
    ).count()


def already_sent(unit_name):
    recipient = TRT3_INDIVIDUAL_UNITS[unit_name]["email"]
    return AjtSendLog.query.filter_by(
        tribunal="TRT-3",
        secretariat=unit_name,
        recipient=recipient,
        result="sent",
    ).first() is not None


def main():
    delay = max(90.0, float(os.environ.get("AJT_BATCH_DELAY_SECONDS", "90")))
    daily_limit = max(1, int(os.environ.get("AJT_DAILY_LIMIT", "10")))
    max_batch = min(len(TRT3_BATCH_1), max(1, int(os.environ.get("AJT_BATCH_MAX", "10"))))

    with app.app_context():
        sent = 0
        skipped = 0
        errors = 0

        print({
            "event": "trt3_lote1_start",
            "targets": TRT3_BATCH_1,
            "today_sent_before": sent_today_count(),
            "daily_limit": daily_limit,
            "delay_seconds": delay,
            "max_batch": max_batch,
        }, flush=True)

        processed = 0
        for unit_name in TRT3_BATCH_1:
            if processed >= max_batch:
                break
            processed += 1

            if already_sent(unit_name):
                skipped += 1
                print({
                    "event": "duplicate_skipped",
                    "unit": unit_name,
                    "recipient": TRT3_INDIVIDUAL_UNITS[unit_name]["email"],
                }, flush=True)
                continue

            if sent_today_count() >= daily_limit:
                print({
                    "event": "daily_limit_stop",
                    "today_sent": sent_today_count(),
                    "daily_limit": daily_limit,
                }, flush=True)
                break

            try:
                recipient, _, provider_id = send_trt3_individual_email(unit_name)
                sent += 1
                print({
                    "event": "sent",
                    "unit": unit_name,
                    "recipient": recipient,
                    "provider_id": provider_id,
                }, flush=True)
            except Exception as exc:
                errors += 1
                print({
                    "event": "error",
                    "unit": unit_name,
                    "recipient": TRT3_INDIVIDUAL_UNITS[unit_name]["email"],
                    "error": str(exc),
                }, flush=True)

            if unit_name != TRT3_BATCH_1[-1]:
                time.sleep(delay)

        print({
            "event": "trt3_lote1_finished",
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
            "today_sent_after": sent_today_count(),
        }, flush=True)


if __name__ == "__main__":
    main()
