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

TRT3_INDIVIDUAL_UNITS = {
    "1ª Vara do Trabalho de Sete Lagoas": {"city":"Sete Lagoas","email":"vt1.setelagoas@trt3.jus.br","forum_already_contacted":True},
    "2ª Vara do Trabalho de Sete Lagoas": {"city":"Sete Lagoas","email":"vt2.setelagoas@trt3.jus.br","forum_already_contacted":True},
    "3ª Vara do Trabalho de Sete Lagoas": {"city":"Sete Lagoas","email":"vt3.setelagoas@trt3.jus.br","forum_already_contacted":True},
    "1ª Vara do Trabalho de Contagem": {"city":"Contagem","email":"vt1.contagem@trt3.jus.br"},
    "2ª Vara do Trabalho de Contagem": {"city":"Contagem","email":"vt2.contagem@trt3.jus.br"},
    "3ª Vara do Trabalho de Contagem": {"city":"Contagem","email":"vt3.contagem@trt3.jus.br"},
    "4ª Vara do Trabalho de Contagem": {"city":"Contagem","email":"vt4.contagem@trt3.jus.br"},
    "5ª Vara do Trabalho de Contagem": {"city":"Contagem","email":"vt5.contagem@trt3.jus.br"},
    "6ª Vara do Trabalho de Contagem": {"city":"Contagem","email":"vt6.contagem@trt3.jus.br"},
    "Vara do Trabalho de Santa Luzia": {"city":"Santa Luzia","email":"vt.santaluzia@trt3.jus.br"},
}

TRT3_BATCH_1 = list(TRT3_INDIVIDUAL_UNITS.keys())

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


def build_trt3_individual_message(unit_name):
    config = TRT3_INDIVIDUAL_UNITS.get(unit_name)
    if not config:
        raise RuntimeError("Unidade TRT-3 fora do lote autorizado.")
    row = AjtVaraLink.query.filter_by(tribunal="TRT-3", vara=unit_name).first()
    if not row:
        row = AjtVaraLink(tribunal="TRT-3", secretariat=unit_name, contact_email=config["email"], city=config["city"], vara=unit_name, status="Não solicitado")
        db.session.add(row)
    else:
        row.secretariat, row.contact_email, row.city = unit_name, config["email"], config["city"]
    db.session.commit()
    prior = ""
    if config.get("forum_already_contacted"):
        prior = "\nA apresentação institucional já foi anteriormente encaminhada ao Foro do Trabalho de Sete Lagoas. Neste contato, apresento especificamente minha disponibilidade para atuação perante esta Vara.\n"
    subject = "Disponibilidade para atuação pericial — AJ/JT"
    body = """À {unit},

Prezados(as),

Meu nome é Hugo Mendes da Silva, advogado inscrito na OAB/SP nº 437.005 e OAB/MG nº 161.454, pós-graduado em Direito do Trabalho e profissional regularmente cadastrado no Sistema AJ/JT e no perfil Perito do PJe do TRT da 3ª Região.
{prior}
Atuo tecnicamente com cálculos trabalhistas, liquidação de sentença, conferência de cálculos, atualização de créditos e elaboração de cálculos no PJe-Calc.

Venho apresentar minha disponibilidade para atuação como perito calculista perante esta unidade, para futuras nomeações, conforme a necessidade do Juízo.

Encaminho, em anexo, meu currículo pericial para apreciação.

Permaneço à disposição para quaisquer informações adicionais.

Atenciosamente,

Hugo Mendes da Silva
Perito calculista cadastrado no Sistema AJ/JT
OAB/SP 437.005 | OAB/MG 161.454
HM Perícia & Cálculos
hugo@hmpericia.com.br
(31) 99587-1227
""".format(unit=unit_name, prior=prior)
    return subject, body, row, config


def send_trt3_individual_email(unit_name):
    if unit_name not in TRT3_INDIVIDUAL_UNITS:
        raise RuntimeError("Unidade TRT-3 fora do lote autorizado.")
    if not env_bool("AJT_SEND_ENABLED", False):
        raise RuntimeError("Envios AJ/JT estão bloqueados.")
    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")
    curriculum = AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first()
    if not curriculum:
        raise RuntimeError("Currículo pericial não cadastrado no módulo AJ/JT.")
    subject, body, row, config = build_trt3_individual_message(unit_name)
    recipient = config["email"]
    previous = AjtSendLog.query.filter_by(tribunal="TRT-3", secretariat=unit_name, recipient=recipient, result="sent").first()
    if previous:
        raise RuntimeError("Já existe envio concluído para esta Vara. O sistema bloqueia duplicidade.")
    daily_limit = max(1, int(os.environ.get("AJT_DAILY_LIMIT", "10")))
    if ajt_sent_today_count() >= daily_limit:
        raise RuntimeError("Limite AJ/JT diário atingido.")
    html_body = "<!doctype html><html><body><div style='max-width:720px;margin:auto;padding:20px'>" + text_to_html(body) + "</div></body></html>"
    try:
        provider_response = send_via_resend(recipient=recipient, subject=subject, text_body=body, html_body=html_body, attachments=[{"filename":curriculum.filename,"data":curriculum.data}])
    except Exception as exc:
        db.session.add(AjtSendLog(tribunal="TRT-3", secretariat=unit_name, recipient=recipient, subject=subject, result="error", detail=str(exc)[:2000]))
        db.session.commit()
        raise
    now = datetime.now(timezone.utc)
    row.status = "Solicitação enviada"
    row.requested_at = row.requested_at or now
    row.updated_at = now
    provider_id = str(provider_response.get("id") or "") if isinstance(provider_response, dict) else ""
    db.session.add(AjtSendLog(tribunal="TRT-3", secretariat=unit_name, recipient=recipient, subject=subject, result="sent", detail=("Resend ID: " + provider_id) if provider_id else None))
    db.session.commit()
    return recipient, 1, provider_id
