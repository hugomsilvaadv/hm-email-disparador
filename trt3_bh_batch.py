# TRT-3 Belo Horizonte batch — controlled institutional dispatch
import html
import os
import time
from datetime import datetime, timezone

from app import (
    AjtCurriculum,
    AjtSendLog,
    AjtUnit,
    AjtVaraLink,
    SendLog,
    app,
    db,
    resend_config_ready,
    send_via_resend,
    text_to_html,
)

BH_TOTAL_VARAS = 48
SOURCE_URL = "https://www.tst.jus.br/documents/18640430/24404697/End03.pdf/81f775dc-5c16-a83d-a024-2a22864ea499"


def today_total_sent():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    commercial = SendLog.query.filter(
        SendLog.sent_at >= start,
        SendLog.result == "sent",
    ).count()
    ajt = AjtSendLog.query.filter(
        AjtSendLog.sent_at >= start,
        AjtSendLog.result == "sent",
    ).count()
    return commercial + ajt


def vara_data(number):
    return {
        "number": number,
        "unit": f"{number}ª Vara do Trabalho de Belo Horizonte",
        "email": f"varabh{number}@trt3.jus.br",
        "code": (
            f"{number:04d}" if number <= 25 else
            str({
                26: 105, 27: 106, 28: 107, 29: 108, 30: 109,
                31: 110, 32: 111, 33: 112, 34: 113, 35: 114,
                36: 136, 37: 137, 38: 138, 39: 139, 40: 140,
                41: 179, 42: 180, 43: 181, 44: 182, 45: 183,
                46: 184, 47: 185, 48: 186,
            }[number]).zfill(4)
        ),
    }


def build_message(unit):
    subject = "Disponibilidade para atuação pericial — AJ/JT"
    body = f"""À Secretaria da {unit},

Prezados(as),

Meu nome é Hugo Mendes da Silva, advogado inscrito na OAB/SP nº 437.005 e OAB/MG nº 161.454, pós-graduado em Direito do Trabalho e profissional regularmente cadastrado no Sistema AJ/JT e no perfil Perito do PJe do TRT da 3ª Região.

Atuo tecnicamente com cálculos trabalhistas, liquidação de sentença, conferência de cálculos, atualização de créditos e elaboração de cálculos no PJe-Calc.

Venho apresentar minha disponibilidade para atuação como perito calculista perante esta Vara e, se cabível, solicitar minha disponibilização/vinculação para futuras nomeações.

Tenho disponibilidade para atendimento remoto e, quando necessário, comparecimento presencial em Belo Horizonte e região.

Encaminho, em anexo, meu currículo pericial para apreciação.

Permaneço à disposição para quaisquer informações adicionais ou procedimento específico exigido por esta unidade.

Atenciosamente,

Hugo Mendes da Silva
Perito calculista cadastrado no Sistema AJ/JT
OAB/SP 437.005 | OAB/MG 161.454
HM Perícia & Cálculos
hugo@hmpericia.com.br
(31) 99587-1227
"""
    return subject, body


def already_sent(unit, email):
    return AjtSendLog.query.filter_by(
        tribunal="TRT-3",
        secretariat=unit,
        recipient=email,
        result="sent",
    ).first() is not None


def seed_unit(data):
    unit = AjtUnit.query.filter_by(
        tribunal="TRT-3",
        unit=data["unit"],
    ).first()
    if not unit:
        unit = AjtUnit(
            tribunal="TRT-3",
            city="Belo Horizonte",
            unit=data["unit"],
            email=data["email"],
            source_url=SOURCE_URL,
            status="Não contatado",
            notes=f"Código TRT: {data['code']}. Jurisdição: Belo Horizonte.",
        )
        db.session.add(unit)
    else:
        unit.email = data["email"]
        unit.source_url = SOURCE_URL
        unit.notes = f"Código TRT: {data['code']}. Jurisdição: Belo Horizonte."

    link = AjtVaraLink.query.filter_by(
        tribunal="TRT-3",
        vara=data["unit"],
    ).first()
    if not link:
        link = AjtVaraLink(
            tribunal="TRT-3",
            secretariat="Belo Horizonte — envio individual",
            contact_email=data["email"],
            city="Belo Horizonte",
            vara=data["unit"],
            status="Não solicitado",
            notes=f"Código TRT: {data['code']}.",
        )
        db.session.add(link)
    else:
        link.secretariat = "Belo Horizonte — envio individual"
        link.contact_email = data["email"]
        link.city = "Belo Horizonte"
    db.session.flush()
    return unit, link


def send_one(data, curriculum):
    unit, link = seed_unit(data)
    if already_sent(data["unit"], data["email"]):
        return "duplicate", None

    subject, body = build_message(data["unit"])
    html_body = (
        "<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;color:#222;background:#fff'>"
        "<div style='max-width:720px;margin:auto;padding:20px'>"
        + text_to_html(body)
        + "</div></body></html>"
    )

    try:
        provider_response = send_via_resend(
            recipient=data["email"],
            subject=subject,
            text_body=body,
            html_body=html_body,
            attachments=[{"filename": curriculum.filename, "data": curriculum.data}],
        )
    except Exception as exc:
        db.session.add(AjtSendLog(
            tribunal="TRT-3",
            secretariat=data["unit"],
            recipient=data["email"],
            subject=subject,
            result="error",
            detail=str(exc)[:2000],
        ))
        db.session.commit()
        raise

    now = datetime.now(timezone.utc)
    provider_id = ""
    if isinstance(provider_response, dict):
        provider_id = str(provider_response.get("id") or "")

    unit.status = "Apresentação enviada"
    unit.last_contact = now
    link.status = "Solicitação enviada"
    link.requested_at = link.requested_at or now
    link.updated_at = now

    db.session.add(AjtSendLog(
        tribunal="TRT-3",
        secretariat=data["unit"],
        recipient=data["email"],
        subject=subject,
        result="sent",
        detail=(f"Resend ID: {provider_id}" if provider_id else None),
    ))
    db.session.commit()
    return "sent", provider_id


def main():
    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")

    daily_cap = max(1, int(os.environ.get("RESEND_DAILY_CAP", "100")))
    reserve = max(0, int(os.environ.get("RESEND_DAILY_RESERVE", "3")))
    delay = max(1.0, float(os.environ.get("AJT_BATCH_DELAY_SECONDS", "2")))
    max_batch = min(BH_TOTAL_VARAS, max(1, int(os.environ.get("AJT_BATCH_MAX", "48"))))

    with app.app_context():
        curriculum = AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first()
        if not curriculum:
            raise RuntimeError("Currículo pericial não cadastrado no módulo AJ/JT.")

        sent = 0
        skipped = 0
        errors = 0

        print({
            "event": "bh_batch_start",
            "today_total_before": today_total_sent(),
            "daily_cap": daily_cap,
            "reserve": reserve,
            "max_batch": max_batch,
        }, flush=True)

        for number in range(1, BH_TOTAL_VARAS + 1):
            if sent + skipped >= max_batch:
                break

            current_total = today_total_sent()
            if current_total >= max(0, daily_cap - reserve):
                print({
                    "event": "daily_cap_stop",
                    "today_total": current_total,
                    "daily_cap": daily_cap,
                    "reserve": reserve,
                }, flush=True)
                break

            data = vara_data(number)
            try:
                status, provider_id = send_one(data, curriculum)
                if status == "sent":
                    sent += 1
                    print({
                        "event": "sent",
                        "vara": data["unit"],
                        "recipient": data["email"],
                        "provider_id": provider_id,
                    }, flush=True)
                    time.sleep(delay)
                else:
                    skipped += 1
                    print({
                        "event": "duplicate_skipped",
                        "vara": data["unit"],
                        "recipient": data["email"],
                    }, flush=True)
            except Exception as exc:
                errors += 1
                print({
                    "event": "error",
                    "vara": data["unit"],
                    "recipient": data["email"],
                    "error": str(exc),
                }, flush=True)
                if "429" in str(exc) or "daily" in str(exc).lower() or "quota" in str(exc).lower():
                    break
                time.sleep(delay)

        print({
            "event": "bh_batch_finished",
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
            "today_total_after": today_total_sent(),
        }, flush=True)


if __name__ == "__main__":
    main()
