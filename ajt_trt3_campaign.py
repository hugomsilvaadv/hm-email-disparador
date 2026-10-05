import json
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

TRT3_GROUPS = {
    "SETE_LAGOAS": {
        "label": "Sete Lagoas — Varas individuais",
        "source_url": "https://www.tst.jus.br/documents/18640430/24404697/End03.pdf/81f775dc-5c16-a83d-a024-2a22864ea499",
        "targets": [
            ("1ª Vara do Trabalho de Sete Lagoas", "vt1.setelagoas@trt3.jus.br"),
            ("2ª Vara do Trabalho de Sete Lagoas", "vt2.setelagoas@trt3.jus.br"),
            ("3ª Vara do Trabalho de Sete Lagoas", "vt3.setelagoas@trt3.jus.br"),
        ],
        "context": "Informo que já encaminhei apresentação institucional ao Foro do Trabalho de Sete Lagoas e, neste contato, apresento minha disponibilidade especificamente perante esta Vara.",
    },
    "CONTAGEM": {
        "label": "Contagem — Varas individuais",
        "source_url": "https://portal.trt3.jus.br/internet/conheca-o-trt/comunicacao/noticias-institucionais/problemas-no-pabx-de-contagem",
        "targets": [
            ("1ª Vara do Trabalho de Contagem", "vt1.contagem@trt3.jus.br"),
            ("2ª Vara do Trabalho de Contagem", "vt2.contagem@trt3.jus.br"),
            ("3ª Vara do Trabalho de Contagem", "vt3.contagem@trt3.jus.br"),
            ("4ª Vara do Trabalho de Contagem", "vt4.contagem@trt3.jus.br"),
            ("5ª Vara do Trabalho de Contagem", "vt5.contagem@trt3.jus.br"),
            ("6ª Vara do Trabalho de Contagem", "vt6.contagem@trt3.jus.br"),
        ],
        "context": "",
    },
    "SANTA_LUZIA": {
        "label": "Santa Luzia — Vara única",
        "source_url": "https://portal.trt3.jus.br/internet/servicos/atermacao-virtual/@@trt3-atermacao-jurisdicao",
        "targets": [
            ("Vara do Trabalho de Santa Luzia", "vt.santaluzia@trt3.jus.br"),
        ],
        "context": "",
    },

    "RMBH_EXPANSAO_1": {
        "label": "RMBH/entorno — expansão 1",
        "source_url": "https://www.tst.jus.br/documents/18640430/24404697/End03.pdf/81f775dc-5c16-a83d-a024-2a22864ea499",
        "targets": [
            ("1ª Vara do Trabalho de Betim", "vt1.betim@trt3.jus.br"),
            ("2ª Vara do Trabalho de Betim", "vt2.betim@trt3.jus.br"),
            ("3ª Vara do Trabalho de Betim", "vt3.betim@trt3.jus.br"),
            ("4ª Vara do Trabalho de Betim", "vt4.betim@trt3.jus.br"),
            ("5ª Vara do Trabalho de Betim", "vt5.betim@trt3.jus.br"),
            ("6ª Vara do Trabalho de Betim", "vt6.betim@trt3.jus.br"),
            ("1ª Vara do Trabalho de Nova Lima", "vt1.novalima@trt3.jus.br"),
            ("2ª Vara do Trabalho de Nova Lima", "vt2.novalima@trt3.jus.br"),
            ("1ª Vara do Trabalho de Pedro Leopoldo", "vt1.pedroleopoldo@trt3.jus.br"),
            ("2ª Vara do Trabalho de Pedro Leopoldo", "vt2.pedroleopoldo@trt3.jus.br"),
            ("Vara do Trabalho de Ribeirão das Neves", "vt.ribeiraodasneves@trt3.jus.br"),
            ("Vara do Trabalho de Sabará", "vt.sabara@trt3.jus.br"),
        ],
        "context": "",
    },
    "CENTRO_OESTE_1": {
        "label": "Centro-Oeste/Central de Minas — expansão 1",
        "source_url": "https://www.tst.jus.br/documents/18640430/24404697/End03.pdf/81f775dc-5c16-a83d-a024-2a22864ea499",
        "targets": [
            ("1ª Vara do Trabalho de Divinópolis", "vt1.divinopolis@trt3.jus.br"),
            ("2ª Vara do Trabalho de Divinópolis", "vt2.divinopolis@trt3.jus.br"),
            ("Vara do Trabalho de Pará de Minas", "vt.parademinas@trt3.jus.br"),
            ("Vara do Trabalho de Itaúna", "vt.itauna@trt3.jus.br"),
            ("Vara do Trabalho de Bom Despacho", "vt.bomdespacho@trt3.jus.br"),
            ("Vara do Trabalho de Curvelo", "vt.curvelo@trt3.jus.br"),
            ("1ª Vara do Trabalho de Congonhas", "vt1.congonhas@trt3.jus.br"),
            ("Vara do Trabalho de Conselheiro Lafaiete", "vt.lafaiete@trt3.jus.br"),
            ("Vara do Trabalho de Diamantina", "vt.diamantina@trt3.jus.br"),
        ],
        "context": "",
    },
}


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


def build_message(unit, context=""):
    subject = "Disponibilidade para futuras nomeações — perito calculista | AJ/JT / PJe TRT-3"
    extra = f"\n{context}\n" if context else ""
    body = f"""À Secretaria da {unit},

Prezados(as),

Meu nome é Hugo Mendes da Silva, advogado inscrito na OAB/SP nº 437.005 e OAB/MG nº 161.454, pós-graduado em Direito do Trabalho e perito calculista com cadastro nos sistemas oficiais da Justiça do Trabalho, inclusive no Sistema AJ/JT e no perfil Perito do PJe do TRT da 3ª Região.

Atuo com cálculos trabalhistas e PJe-Calc, incluindo liquidação de sentença, atualização de créditos, conferência de cálculos e apoio técnico em impugnações.
{extra}
Escrevo apenas para registrar minha disponibilidade para futuras nomeações como perito calculista perante esta unidade, caso haja necessidade e conforme os critérios do Juízo.

Tenho disponibilidade para atuação remota e, quando necessário, presencial mediante alinhamento.

Meu currículo pericial segue anexo apenas para referência, sem necessidade de qualquer providência ou resposta a este e-mail.

Permaneço à disposição.

Atenciosamente,

Hugo Mendes da Silva
Perito calculista | AJ/JT / PJe TRT-3
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


def upsert_tracking(unit_name, email, source_url):
    now = datetime.now(timezone.utc)
    contact = AjtUnit.query.filter_by(tribunal="TRT-3", unit=unit_name).first()
    if not contact:
        contact = AjtUnit(
            tribunal="TRT-3",
            city=unit_name.split(" de ")[-1],
            unit=unit_name,
            email=email,
            source_url=source_url,
            status="Apresentação enviada",
            last_contact=now,
            notes="Campanha individual TRT-3.",
        )
        db.session.add(contact)
    else:
        contact.email = email
        contact.source_url = source_url
        contact.status = "Apresentação enviada"
        contact.last_contact = now

    link = AjtVaraLink.query.filter_by(tribunal="TRT-3", vara=unit_name).first()
    if not link:
        city = unit_name.split(" de ")[-1]
        link = AjtVaraLink(
            tribunal="TRT-3",
            secretariat=f"{city} — envio individual",
            contact_email=email,
            city=city,
            vara=unit_name,
            status="Apresentação enviada",
            requested_at=now,
            notes="Campanha individual TRT-3.",
        )
        db.session.add(link)
    else:
        link.contact_email = email
        link.status = "Apresentação enviada"
        link.requested_at = link.requested_at or now
        link.updated_at = now


def send_group(group_key):
    group_key = group_key.strip().upper()
    group = TRT3_GROUPS.get(group_key)
    if not group:
        raise RuntimeError(f"Grupo TRT-3 inválido: {group_key}")

    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")

    curriculum = AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first()
    if not curriculum:
        raise RuntimeError("Currículo pericial não cadastrado no módulo AJ/JT.")

    delay = max(30, int(os.environ.get("AJT_BATCH_DELAY_SECONDS", "90")))
    daily_cap = max(1, int(os.environ.get("RESEND_DAILY_CAP", "100")))
    reserve = max(0, int(os.environ.get("RESEND_DAILY_RESERVE", "5")))

    summary = {"group": group_key, "sent": 0, "skipped": 0, "errors": []}
    for unit_name, email in group["targets"]:
        if today_total_sent() >= max(0, daily_cap - reserve):
            summary["errors"].append({
                "unit": unit_name,
                "email": email,
                "error": "Limite diário de segurança atingido.",
            })
            break

        if already_sent(unit_name, email):
            summary["skipped"] += 1
            print(json.dumps({
                "event": "duplicate_skipped",
                "group": group_key,
                "unit": unit_name,
                "recipient": email,
            }, ensure_ascii=False), flush=True)
            continue

        subject, body = build_message(unit_name, group.get("context", ""))
        html_body = (
            "<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;color:#222;background:#fff'>"
            "<div style='max-width:720px;margin:auto;padding:20px'>"
            + text_to_html(body)
            + "</div></body></html>"
        )

        try:
            response = send_via_resend(
                recipient=email,
                subject=subject,
                text_body=body,
                html_body=html_body,
                attachments=[{"filename": curriculum.filename, "data": curriculum.data}],
            )
            provider_id = str(response.get("id") or "") if isinstance(response, dict) else ""
            upsert_tracking(unit_name, email, group["source_url"])
            db.session.add(AjtSendLog(
                tribunal="TRT-3",
                secretariat=unit_name,
                recipient=email,
                subject=subject,
                result="sent",
                detail=(f"Resend ID: {provider_id}" if provider_id else None),
            ))
            db.session.commit()
            summary["sent"] += 1
            print(json.dumps({
                "event": "sent",
                "group": group_key,
                "unit": unit_name,
                "recipient": email,
                "provider_id": provider_id or None,
            }, ensure_ascii=False), flush=True)
        except Exception as exc:
            db.session.rollback()
            db.session.add(AjtSendLog(
                tribunal="TRT-3",
                secretariat=unit_name,
                recipient=email,
                subject=subject,
                result="error",
                detail=str(exc)[:2000],
            ))
            db.session.commit()
            summary["errors"].append({
                "unit": unit_name,
                "email": email,
                "error": str(exc),
            })
            print(json.dumps({
                "event": "error",
                "group": group_key,
                "unit": unit_name,
                "recipient": email,
                "error": str(exc),
            }, ensure_ascii=False), flush=True)

        if unit_name != group["targets"][-1][0]:
            time.sleep(delay)

    print(json.dumps({"event": "group_finished", **summary}, ensure_ascii=False), flush=True)
    return summary


def main():
    group_key = os.environ.get("AJT_TRT3_GROUP", "").strip()
    if not group_key:
        raise RuntimeError("AJT_TRT3_GROUP não informado.")
    with app.app_context():
        send_group(group_key)


if __name__ == "__main__":
    main()
