import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app import app, db, Lead, send_email_for_lead

TZ = ZoneInfo("America/Sao_Paulo")


def main():
    expected_date = os.environ.get("SCHEDULED_RUN_DATE", "").strip()
    today = datetime.now(TZ).date().isoformat()

    if expected_date and today != expected_date:
        print(f"Execução ignorada: hoje={today}, agendado={expected_date}")
        return

    target_time = os.environ.get("SCHEDULED_RUN_TIME", "09:17").strip()
    try:
        target_hour, target_minute = [int(part) for part in target_time.split(":", 1)]
        now = datetime.now(TZ)
        target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        wait_seconds = (target - now).total_seconds()
        if wait_seconds > 0:
            print(f"Aguardando {int(wait_seconds)}s até {target_time} America/Sao_Paulo")
            time.sleep(wait_seconds)
    except Exception as exc:
        raise RuntimeError(f"SCHEDULED_RUN_TIME inválido: {target_time}") from exc

    raw = os.environ.get("SCHEDULED_LEADS", "").strip()
    emails = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not emails:
        raise RuntimeError("SCHEDULED_LEADS não configurado.")

    interval = max(10, int(os.environ.get("MIN_INTERVAL_SECONDS", "180")))

    with app.app_context():
        sent = 0
        skipped = 0
        errors = 0

        for index, email in enumerate(emails):
            lead = Lead.query.filter(db.func.lower(Lead.email) == email).first()

            if not lead:
                print(f"Lead não encontrado: {email}")
                errors += 1
                continue

            if lead.status != "Não contatado":
                print(f"Ignorado {lead.office}: status atual={lead.status}")
                skipped += 1
                continue

            try:
                send_email_for_lead(lead)
                sent += 1
                print(f"Enviado: {lead.office} <{lead.email}>")
            except Exception as exc:
                errors += 1
                print(f"Erro em {lead.office} <{lead.email}>: {exc}")

            if index < len(emails) - 1:
                time.sleep(interval)

        print(f"Concluído: enviados={sent}, ignorados={skipped}, erros={errors}")


if __name__ == "__main__":
    main()
