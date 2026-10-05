from datetime import datetime
from zoneinfo import ZoneInfo

from app import AjtSendLog, app, send_trt15_secretariat_email
from ajt_trt15_campaign import run_group

TZ = ZoneInfo("America/Sao_Paulo")

# Lotes originais preservados apenas para histórico/auditoria.
DATE_GROUPS = {
    "2026-09-30": "WED",
    "2026-10-01": "THU",
    "2026-10-02": "FRI",
}

# Reenvios controlados: endereços continuam publicados oficialmente pelo TRT-15
# e não constam na lista de supressões do Resend.
RETRY_DATES = {
    "2026-10-06": "Araraquara",
    "2026-10-07": "Piracicaba",
    "2026-10-08": "Bauru",
}


def retry_already_sent(secretariat):
    return AjtSendLog.query.filter(
        AjtSendLog.tribunal == "TRT-15",
        AjtSendLog.secretariat == secretariat,
        AjtSendLog.result == "sent",
        AjtSendLog.detail.ilike("%retry_after_bounce%"),
    ).first() is not None


def main():
    today = datetime.now(TZ).date().isoformat()

    retry_secretariat = RETRY_DATES.get(today)
    if retry_secretariat:
        print({
            "event": "trt15_retry_scheduled_start",
            "date": today,
            "secretariat": retry_secretariat,
        }, flush=True)

        with app.app_context():
            if retry_already_sent(retry_secretariat):
                print({
                    "event": "trt15_retry_duplicate_skipped",
                    "date": today,
                    "secretariat": retry_secretariat,
                }, flush=True)
                return

            try:
                recipient, total_varas = send_trt15_secretariat_email(
                    retry_secretariat,
                    allow_retry=True,
                )
                print({
                    "event": "trt15_retry_sent",
                    "date": today,
                    "secretariat": retry_secretariat,
                    "recipient": recipient,
                    "total_varas": total_varas,
                }, flush=True)
            except Exception as exc:
                print({
                    "event": "trt15_retry_error",
                    "date": today,
                    "secretariat": retry_secretariat,
                    "error": str(exc),
                }, flush=True)
                raise
        return

    group = DATE_GROUPS.get(today)
    if group:
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
        return

    print({
        "event": "trt15_no_batch_today",
        "date": today,
        "known_dates": sorted(set(DATE_GROUPS) | set(RETRY_DATES)),
    }, flush=True)


if __name__ == "__main__":
    main()

# Railway deploy trigger: TRT-15 institutional-message retries
