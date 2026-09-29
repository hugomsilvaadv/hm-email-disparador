import html
import os
from datetime import datetime, timezone

from app import (
    AjtCurriculum,
    AjtSendLog,
    AjtUnit,
    AjtVaraLink,
    ajt_sent_today_count,
    db,
    env_bool,
    resend_config_ready,
    send_via_resend,
    text_to_html,
)

TRT3_FORUMS = {
    "Sete Lagoas": {
        "unit": "Foro do Trabalho de Sete Lagoas",
        "email": "foro.setelagoas@trt3.jus.br",
        "address": "Alameda Ismael Martins, 101 - Sete Lagoas/MG",
        "source_url": "https://portal.trt3.jus.br/internet/servicos/atermacao-virtual/@@trt3-atermacao-jurisdicao",
        "varas": [
            "1ª Vara do Trabalho de Sete Lagoas",
            "2ª Vara do Trabalho de Sete Lagoas",
            "3ª Vara do Trabalho de Sete Lagoas",
        ],
    }
}


def seed_trt3_forum(secretariat):
    config = TRT3_FORUMS.get(secretariat)
    if not config:
        raise RuntimeError("Foro TRT-3 inválido.")

    contact = AjtUnit.query.filter_by(
        tribunal="TRT-3",
        unit=config["unit"],
    ).first()
    if not contact:
        contact = AjtUnit(
            tribunal="TRT-3",
            city=secretariat,
            unit=config["unit"],
            email=config["email"],
            address=config["address"],
            source_url=config["source_url"],
            status="Não contatado",
        )
        db.session.add(contact)
    else:
        contact.email = config["email"]
        contact.address = config["address"]
        contact.source_url = config["source_url"]

    for vara_name in config["varas"]:
        row = AjtVaraLink.query.filter_by(
            tribunal="TRT-3",
            vara=vara_name,
        ).first()
        if not row:
            db.session.add(AjtVaraLink(
                tribunal="TRT-3",
                secretariat=secretariat,
                contact_email=config["email"],
                city=secretariat,
                vara=vara_name,
                status="Não solicitado",
            ))
        else:
            row.secretariat = secretariat
            row.contact_email = config["email"]
            row.city = secretariat

    db.session.commit()
    return config


def build_trt3_forum_message(secretariat):
    config = seed_trt3_forum(secretariat)
    rows = AjtVaraLink.query.filter_by(
        tribunal="TRT-3",
        secretariat=secretariat,
    ).filter(
        AjtVaraLink.status != "Não atuar"
    ).order_by(AjtVaraLink.vara.asc()).all()

    vara_list = "\n".join(f"- {row.vara}" for row in rows)
    subject = "Disponibilidade para atuação pericial e vinculação — AJ/JT"

    body = f"""Ao Foro do Trabalho de {secretariat},

Prezados(as),

Meu nome é Hugo Mendes da Silva, advogado inscrito na OAB/SP nº 437.005 e OAB/MG nº 161.454, pós-graduado em Direito do Trabalho e profissional regularmente cadastrado no Sistema AJ/JT e no perfil Perito do PJe do TRT da 3ª Região.

Atuo tecnicamente com cálculos trabalhistas, liquidação de sentença, conferência de cálculos, atualização de créditos e elaboração de cálculos no PJe-Calc.

Venho apresentar minha disponibilidade para atuação como perito calculista perante as unidades de {secretariat} e, se cabível, solicitar orientação ou encaminhamento quanto à disponibilização/vinculação para futuras nomeações nas seguintes Varas:

{vara_list}

Encaminho, em anexo, meu currículo pericial para apreciação.

Caso o procedimento de vinculação deva ser realizado diretamente perante cada Vara ou por outro canal específico, agradeço se puderem me orientar quanto ao procedimento adequado.

Permaneço à disposição para quaisquer informações adicionais.

Atenciosamente,

Hugo Mendes da Silva
Perito calculista cadastrado no Sistema AJ/JT
OAB/SP 437.005 | OAB/MG 161.454
HM Perícia & Cálculos
hugo@hmpericia.com.br
(31) 99587-1227
"""
    return subject, body, rows, config


def send_trt3_forum_email(secretariat):
    if secretariat not in TRT3_FORUMS:
        raise RuntimeError("Foro TRT-3 inválido.")
    if not env_bool("AJT_SEND_ENABLED", False):
        raise RuntimeError("Envios AJ/JT estão bloqueados.")
    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")

    curriculum = AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first()
    if not curriculum:
        raise RuntimeError("Currículo pericial não cadastrado no módulo AJ/JT.")

    subject, body, rows, config = build_trt3_forum_message(secretariat)
    recipient = config["email"]

    previous = AjtSendLog.query.filter_by(
        tribunal="TRT-3",
        secretariat=secretariat,
        recipient=recipient,
        result="sent",
    ).first()
    if previous:
        raise RuntimeError(
            f"Já existe envio concluído para este Foro em {previous.sent_at.strftime('%d/%m/%Y')}. "
            "O sistema bloqueia duplicidade; eventual novo contato deve ser tratado como follow-up."
        )

    daily_limit = max(1, int(os.environ.get("AJT_DAILY_LIMIT", "2")))
    if ajt_sent_today_count() >= daily_limit:
        raise RuntimeError(f"Limite AJ/JT diário de {daily_limit} unidade(s) atingido.")

    html_body = (
        "<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;color:#222;background:#fff'>"
        "<div style='max-width:720px;margin:auto;padding:20px'>"
        + text_to_html(body)
        + "</div></body></html>"
    )

    try:
        provider_response = send_via_resend(
            recipient=recipient,
            subject=subject,
            text_body=body,
            html_body=html_body,
            attachments=[{"filename": curriculum.filename, "data": curriculum.data}],
        )
    except Exception as exc:
        db.session.add(AjtSendLog(
            tribunal="TRT-3",
            secretariat=secretariat,
            recipient=recipient,
            subject=subject,
            result="error",
            detail=str(exc)[:2000],
        ))
        db.session.commit()
        raise

    now = datetime.now(timezone.utc)
    for row in rows:
        if row.status == "Não solicitado":
            row.status = "Solicitação enviada"
        if not row.requested_at:
            row.requested_at = now
        row.updated_at = now

    contact = AjtUnit.query.filter_by(
        tribunal="TRT-3",
        unit=config["unit"],
    ).first()
    if contact:
        contact.status = "Apresentação enviada"
        contact.last_contact = now

    provider_id = ""
    if isinstance(provider_response, dict):
        provider_id = str(provider_response.get("id") or "")

    db.session.add(AjtSendLog(
        tribunal="TRT-3",
        secretariat=secretariat,
        recipient=recipient,
        subject=subject,
        result="sent",
        detail=(f"Resend ID: {provider_id}" if provider_id else None),
    ))
    db.session.commit()

    return recipient, len(rows), provider_id
