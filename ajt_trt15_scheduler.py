from datetime import datetime
from zoneinfo import ZoneInfo

from app import app
from ajt_trt15_campaign import run_group

TZ = ZoneInfo("America/Sao_Paulo")

DATE_GROUPS = {
    "2026-09-30": "WED",
    "2026-10-01": "THU",
    "2026-10-02": "FRI",
}


def main():
    today = datetime.now(TZ).date().isoformat()
    group = DATE_GROUPS.get(today)

    if not group:
        print({
            "event": "trt15_no_batch_today",
            "date": today,
            "known_dates": sorted(DATE_GROUPS),
        }, flush=True)
        return

    print({
        "event": "trt15_scheduled_start",
        "date": today,
        "group": group,
    }, flush=True)

    with app.app_context():
        summary = run_group(group)

    print({
        "event": "trt15_scheduled_finished",
        "date": today,
        "group": group,
        "summary": summary,
    }, flush=True)


if __name__ == "__main__":
    main()

# Railway deploy trigger: scheduler activation
