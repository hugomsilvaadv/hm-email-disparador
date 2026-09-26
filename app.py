import csv
import html
import hmac
import io
import os
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-production")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db_url = os.environ.get("DATABASE_URL", "sqlite:///hm_email.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://") and "+psycopg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url

db = SQLAlchemy(app)

STATUS_OPTIONS = [
    "Não contatado",
    "Enviado",
    "Respondeu",
    "Reunião agendada",
    "Cliente",
    "Sem interesse",
    "Não contatar",
    "Erro",
]

DEFAULT_SUBJECT = "Apoio especializado em cálculos trabalhistas para seu escritório"
DEFAULT_BODY = """Olá, equipe do {office}, tudo bem?

Meu nome é Hugo Mendes e sou responsável pela HM Perícia & Cálculos, especializada no suporte técnico a escritórios de advocacia na elaboração, conferência e revisão de cálculos trabalhistas.

Identificamos a atuação do escritório{profile_hint} e gostaríamos de apresentar uma possibilidade de apoio técnico terceirizado, especialmente para demandas em que o cálculo exige tempo operacional da equipe jurídica.

Entre os serviços prestados estão:
• elaboração de cálculos trabalhistas no PJe-Calc;
• liquidação de sentença;
• cálculos para iniciais, contestações e acordos;
• conferência e impugnação de cálculos apresentados pela parte contrária;
• atualização de cálculos;
• análise de reflexos, FGTS, INSS, IRPF, juros e correção monetária;
• pareceres e análises técnicas.

Valores iniciais:
• Cálculo trabalhista completo: a partir de R$ 400,00
• Parecer/análise técnica: a partir de R$ 200,00

Os valores podem variar conforme a complexidade do processo, o período contratual, a quantidade de documentos e a extensão do cálculo.

Para escritórios com demanda recorrente ou volume mensal de cálculos, trabalhamos também com condições comerciais específicas.

Nosso objetivo é funcionar como uma extensão técnica do escritório: o advogado nos encaminha os documentos e os comandos judiciais, e devolvemos o cálculo estruturado e conferido, inclusive em PJe-Calc, quando necessário.

Anexo, envio uma apresentação breve da HM Perícia & Cálculos.

Se este tipo de apoio não for pertinente ao escritório, basta nos informar e não enviaremos novas mensagens.

Atenciosamente,
Hugo Mendes
Diretor Técnico | Advogado | Perito Judicial
HM Perícia & Cálculos
WhatsApp: (31) 95349-1100
E-mail: hugo@hmpericia.com.br
hmpericia.com.br
"""


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(120))
    city = db.Column(db.String(120))
    office = db.Column(db.String(240), nullable=False)
    profile = db.Column(db.String(300))
    email = db.Column(db.String(240), nullable=False, index=True)
    whatsapp = db.Column(db.String(80))
    address = db.Column(db.String(400))
    adherence = db.Column(db.String(40))
    source_url = db.Column(db.String(500))
    status = db.Column(db.String(60), default="Não contatado", index=True)
    last_contact = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CampaignAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SendLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), nullable=False, index=True)
    sent_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    recipient = db.Column(db.String(240), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    result = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.Text)
    lead = db.relationship("Lead")


batch_state = {"running": False, "total": 0, "done": 0, "errors": 0, "started_at": None}
batch_lock = threading.Lock()


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def profile_hint(lead):
    return f" na área de {lead.profile}" if lead.profile else ""


def render_body(lead):
    return DEFAULT_BODY.format(office=lead.office, profile_hint=profile_hint(lead))


def text_to_html(text):
    safe = html.escape(text)
    safe = safe.replace("HM Perícia &amp; Cálculos", "<strong>HM Perícia &amp; Cálculos</strong>")
    safe = safe.replace("PJe-Calc", "<strong>PJe-Calc</strong>")
    return "".join(
        f"<p style='margin:0 0 14px 0;line-height:1.55'>{block.replace(chr(10), '<br>')}</p>"
        for block in safe.split("\n\n")
    )


def smtp_config_ready():
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def sent_today_count():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return SendLog.query.filter(SendLog.sent_at >= start, SendLog.result == "sent").count()


def send_email_for_lead(lead):
    if not env_bool("SEND_ENABLED", False):
        raise RuntimeError("Envios estão bloqueados. Defina SEND_ENABLED=true no Railway somente após o teste SMTP.")
    if not smtp_config_ready():
        raise RuntimeError("SMTP_USER/SMTP_PASSWORD ainda não estão configurados.")
    if lead.status == "Não contatar":
        raise RuntimeError("Lead marcado como Não contatar.")

    daily_limit = int(os.environ.get("DAILY_LIMIT", "20"))
    if sent_today_count() >= daily_limit:
        raise RuntimeError(f"Limite diário de {daily_limit} mensagens atingido.")

    smtp_host = os.environ.get("SMTP_HOST", "smtp.titan.email")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    from_name = os.environ.get("FROM_NAME", "Hugo Mendes | HM Perícia & Cálculos")
    subject = os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT)
    body = render_body(lead)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{smtp_user}>"
    msg["To"] = lead.email
    msg["Reply-To"] = smtp_user
    msg.set_content(body)
    msg.add_alternative(
        f"""<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;color:#14283d;background:#ffffff'>
        <div style='max-width:680px;margin:auto;padding:24px'>
          <div style='border-top:5px solid #c9a24a;padding-top:18px'>{text_to_html(body)}</div>
          <div style='margin-top:22px;padding-top:14px;border-top:1px solid #ddd;color:#667;font-size:12px'>
            HM Perícia &amp; Cálculos · Precisão técnica · Informações confiáveis · Decisões seguras
          </div>
        </div></body></html>""",
        subtype="html",
    )

    material = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
    if material:
        if "/" in material.mimetype:
            maintype, subtype = material.mimetype.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(material.data, maintype=maintype, subtype=subtype, filename=material.filename)

    with smtplib.SMTP_SSL(
        smtp_host,
        smtp_port,
        context=ssl.create_default_context(),
        timeout=30,
    ) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)

    lead.status = "Enviado"
    lead.last_contact = datetime.now(timezone.utc)
    lead.last_error = None
    db.session.add(SendLog(lead_id=lead.id, recipient=lead.email, subject=subject, result="sent"))
    db.session.commit()


def batch_worker(lead_ids):
    interval = max(10, int(os.environ.get("MIN_INTERVAL_SECONDS", "120")))
    with app.app_context():
        try:
            for index, lead_id in enumerate(lead_ids):
                lead = db.session.get(Lead, lead_id)
                if not lead:
                    continue
                try:
                    send_email_for_lead(lead)
                except Exception as exc:
                    lead.status = "Erro"
                    lead.last_error = str(exc)[:1000]
                    db.session.add(SendLog(
                        lead_id=lead.id,
                        recipient=lead.email,
                        subject=os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT),
                        result="error",
                        detail=str(exc)[:2000],
                    ))
                    db.session.commit()
                    batch_state["errors"] += 1
                    if "Limite diário" in str(exc) or "bloqueados" in str(exc):
                        break
                finally:
                    batch_state["done"] += 1
                if index < len(lead_ids) - 1:
                    time.sleep(interval)
        finally:
            batch_state["running"] = False


def import_lead_rows(rows):
    imported = 0
    updated = 0
    skipped = 0

    for row in rows:
        office = (row.get("Escritório") or row.get("office") or "").strip()
        email_addr = (row.get("E-mail") or row.get("Email") or row.get("email") or "").strip().lower()
        if not office or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_addr):
            skipped += 1
            continue

        lead = Lead.query.filter(db.func.lower(Lead.email) == email_addr).first()
        payload = {
            "region": (row.get("Região") or row.get("region") or "").strip(),
            "city": (row.get("Cidade") or row.get("city") or "").strip(),
            "office": office,
            "profile": (row.get("Perfil / área") or row.get("Perfil") or row.get("profile") or "").strip(),
            "email": email_addr,
            "whatsapp": (row.get("WhatsApp") or row.get("whatsapp") or "").strip(),
            "address": (row.get("Endereço") or row.get("address") or "").strip(),
            "adherence": (row.get("Aderência") or row.get("adherence") or "").strip(),
            "source_url": (row.get("Fonte pública") or row.get("source_url") or "").strip(),
            "notes": (row.get("Observações") or row.get("notes") or "").strip(),
        }
        if lead:
            for key, value in payload.items():
                if value:
                    setattr(lead, key, value)
            updated += 1
        else:
            db.session.add(Lead(**payload, status="Não contatado"))
            imported += 1

    db.session.commit()
    return imported, updated, skipped


@app.get("/health")
def health():
    return {"ok": True, "service": "hm-email-disparador"}, 200


@app.route("/login", methods=["GET", "POST"])
def login():
    admin_user = os.environ.get("ADMIN_USER", "hugo")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if request.method == "POST":
        supplied_user = request.form.get("username", "")
        supplied_password = request.form.get("password", "")
        valid_user = hmac.compare_digest(supplied_user, admin_user)
        valid_password = bool(admin_password) and hmac.compare_digest(supplied_password, admin_password)
        if valid_user and valid_password:
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        if not admin_password:
            flash("ADMIN_PASSWORD ainda não foi definido no Railway.", "danger")
        else:
            flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html", admin_user=admin_user)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        total=Lead.query.count(),
        pending=Lead.query.filter_by(status="Não contatado").count(),
        sent=Lead.query.filter_by(status="Enviado").count(),
        replies=Lead.query.filter(Lead.status.in_(["Respondeu", "Reunião agendada", "Cliente"])).count(),
        sent_today=sent_today_count(),
        daily_limit=int(os.environ.get("DAILY_LIMIT", "20")),
        send_enabled=env_bool("SEND_ENABLED", False),
        smtp_ready=smtp_config_ready(),
        batch=batch_state.copy(),
        material=CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first(),
    )


@app.route("/leads", methods=["GET", "POST"])
@login_required
def leads():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um CSV de leads.", "warning")
            return redirect(url_for("leads"))
        if not file.filename.lower().endswith(".csv"):
            flash("A importação aceita arquivo CSV.", "danger")
            return redirect(url_for("leads"))
        try:
            raw = file.read().decode("utf-8-sig")
            imported, updated, skipped = import_lead_rows(csv.DictReader(io.StringIO(raw)))
            flash(f"Importação concluída: {imported} novo(s), {updated} atualizado(s), {skipped} ignorado(s).", "success")
        except Exception as exc:
            flash(f"Falha na importação: {exc}", "danger")
        return redirect(url_for("leads"))

    q = Lead.query
    status = request.args.get("status", "")
    region = request.args.get("region", "")
    search = request.args.get("q", "").strip()
    if status:
        q = q.filter(Lead.status == status)
    if region:
        q = q.filter(Lead.region == region)
    if search:
        term = f"%{search}%"
        q = q.filter(db.or_(Lead.office.ilike(term), Lead.city.ilike(term), Lead.email.ilike(term)))
    rows = q.order_by(Lead.adherence.asc(), Lead.city.asc(), Lead.office.asc()).all()
    regions = [r[0] for r in db.session.query(Lead.region).distinct().order_by(Lead.region).all() if r[0]]
    return render_template("leads.html", leads=rows, status_options=STATUS_OPTIONS, regions=regions)


@app.post("/lead/<int:lead_id>/status")
@login_required
def update_status(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    new_status = request.form.get("status")
    if new_status in STATUS_OPTIONS:
        lead.status = new_status
        db.session.commit()
        flash("Status atualizado.", "success")
    return redirect(request.referrer or url_for("leads"))


@app.get("/lead/<int:lead_id>/preview")
@login_required
def preview(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    return render_template(
        "preview.html",
        lead=lead,
        subject=os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT),
        body=render_body(lead),
        send_enabled=env_bool("SEND_ENABLED", False),
    )


@app.post("/lead/<int:lead_id>/send")
@login_required
def send_one(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    try:
        send_email_for_lead(lead)
        flash(f"E-mail enviado para {lead.office} ({lead.email}).", "success")
    except Exception as exc:
        lead.status = "Erro"
        lead.last_error = str(exc)[:1000]
        db.session.commit()
        flash(f"Falha no envio: {exc}", "danger")
    return redirect(url_for("preview", lead_id=lead.id))


@app.post("/send-selected")
@login_required
def send_selected():
    ids = [int(raw) for raw in request.form.getlist("lead_ids") if raw.isdigit()]
    if not ids:
        flash("Selecione pelo menos um lead.", "warning")
        return redirect(url_for("leads"))

    with batch_lock:
        if batch_state["running"]:
            flash("Já existe um lote em execução.", "warning")
            return redirect(url_for("dashboard"))
        batch_state.update({
            "running": True,
            "total": len(ids),
            "done": 0,
            "errors": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        threading.Thread(target=batch_worker, args=(ids,), daemon=True).start()

    flash(f"Lote de {len(ids)} e-mails iniciado. Os envios serão individuais e espaçados.", "success")
    return redirect(url_for("dashboard"))


@app.route("/material", methods=["GET", "POST"])
@login_required
def material():
    current = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um arquivo.", "warning")
        else:
            name = file.filename.strip()
            ext = os.path.splitext(name)[1].lower()
            allowed = {
                ".pdf": "application/pdf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
            }
            if ext not in allowed:
                flash("Use PDF, PNG ou JPG.", "danger")
            else:
                data = file.read()
                if len(data) > 5 * 1024 * 1024:
                    flash("O material deve ter no máximo 5 MB.", "danger")
                else:
                    CampaignAttachment.query.delete()
                    db.session.add(CampaignAttachment(filename=name, mimetype=allowed[ext], data=data))
                    db.session.commit()
                    flash("Material comercial salvo e será anexado aos próximos envios.", "success")
                    current = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
    return render_template("material.html", current=current)


@app.route("/test-email", methods=["GET", "POST"])
@login_required
def test_email():
    if request.method == "POST":
        recipient = request.form.get("recipient", "").strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", recipient):
            flash("Informe um e-mail válido.", "danger")
        elif not smtp_config_ready():
            flash("Configure SMTP_USER e SMTP_PASSWORD no Railway primeiro.", "danger")
        else:
            try:
                smtp_host = os.environ.get("SMTP_HOST", "smtp.titan.email")
                smtp_port = int(os.environ.get("SMTP_PORT", "465"))
                smtp_user = os.environ["SMTP_USER"]
                smtp_password = os.environ["SMTP_PASSWORD"]
                msg = EmailMessage()
                msg["Subject"] = "Teste SMTP — HM Perícia & Cálculos"
                msg["From"] = f"Hugo Mendes | HM Perícia & Cálculos <{smtp_user}>"
                msg["To"] = recipient
                msg.set_content("Teste concluído com sucesso. O disparador da HM está autenticando no SMTP Titan.")
                with smtplib.SMTP_SSL(
                    smtp_host,
                    smtp_port,
                    context=ssl.create_default_context(),
                    timeout=30,
                ) as smtp:
                    smtp.login(smtp_user, smtp_password)
                    smtp.send_message(msg)
                flash("Teste enviado com sucesso.", "success")
            except Exception as exc:
                flash(f"Falha no teste SMTP: {exc}", "danger")

    return render_template(
        "test_email.html",
        smtp_ready=smtp_config_ready(),
        send_enabled=env_bool("SEND_ENABLED", False),
    )


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
