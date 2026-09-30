import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app import Lead, SendLog, app, db, send_email_for_lead

TZ = ZoneInfo("America/Sao_Paulo")


def already_sent(lead):
    return (
        lead.status != "Não contatado"
        or SendLog.query.filter_by(lead_id=lead.id, result="sent").first() is not None
    )


def candidate_query():
    # Prioridade: alta aderência, depois cidade e escritório para ordem estável.
    adherence_rank = db.case(
        (db.func.lower(Lead.adherence) == "alta", 0),
        (db.func.lower(Lead.adherence) == "média", 1),
        else_=2,
    )
    return (
        Lead.query
        .filter(Lead.status == "Não contatado")
        .order_by(adherence_rank.asc(), Lead.city.asc(), Lead.office.asc(), Lead.id.asc())
    )


def main():
    now = datetime.now(TZ)
    if now.weekday() >= 5:
        print({"event": "commercial_skip_weekend", "date": now.date().isoformat()}, flush=True)
        return

    batch_size = max(1, min(5, int(os.environ.get("COMMERCIAL_BATCH_SIZE", "5"))))
    delay = max(180, int(os.environ.get("MIN_INTERVAL_SECONDS", "180")))

    with app.app_context():
        leads = candidate_query().limit(batch_size).all()
        if not leads:
            print({"event": "commercial_no_pending_leads", "date": now.date().isoformat()}, flush=True)
            return

        sent = 0
        skipped = 0
        errors = 0

        print({
            "event": "commercial_batch_start",
            "date": now.date().isoformat(),
            "batch_size": batch_size,
            "delay_seconds": delay,
            "selected": [{"id": l.id, "office": l.office, "email": l.email, "city": l.city, "adherence": l.adherence} for l in leads],
        }, flush=True)

        for idx, lead in enumerate(leads):
            if already_sent(lead):
                skipped += 1
                print({"event": "duplicate_skipped", "lead_id": lead.id, "office": lead.office, "email": lead.email}, flush=True)
                continue

            try:
                send_email_for_lead(lead)
                sent += 1
                log = SendLog.query.filter_by(lead_id=lead.id, result="sent").order_by(SendLog.sent_at.desc()).first()
                provider_id = ""
                if log and log.detail and "Resend ID:" in log.detail:
                    provider_id = log.detail.split("Resend ID:", 1)[1].strip()
                print({
                    "event": "sent",
                    "lead_id": lead.id,
                    "office": lead.office,
                    "email": lead.email,
                    "city": lead.city,
                    "provider_id": provider_id,
                }, flush=True)
            except Exception as exc:
                errors += 1
                lead.status = "Erro"
                lead.last_error = str(exc)[:1000]
                db.session.commit()
                print({
                    "event": "error",
                    "lead_id": lead.id,
                    "office": lead.office,
                    "email": lead.email,
                    "error": str(exc),
                }, flush=True)

            if idx < len(leads) - 1:
                time.sleep(delay)

        remaining = Lead.query.filter_by(status="Não contatado").count()
        print({
            "event": "commercial_batch_finished",
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
            "remaining_not_contacted": remaining,
        }, flush=True)


if __name__ == "__main__":
    main()
