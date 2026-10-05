import base64
import csv
import html
import hmac
import io
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from urllib import error as urllib_error
from urllib import request as urllib_request

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

AJT_STATUS_OPTIONS = [
    "Não contatado",
    "Apresentação enviada",
    "Acusou recebimento",
    "Vinculação solicitada",
    "Vinculado",
    "Sem interesse",
    "Não contatar",
]

AJT_VARA_STATUS_OPTIONS = [
    "Não solicitado",
    "Apresentação enviada",
    "Solicitação enviada",
    "Aguardando análise",
    "Vinculado",
    "Não vinculado",
    "Não atuar",
]

AJT_DEFAULT_SUBJECT = "Disponibilidade para atuação como perito — Sistema AJ/JT"
AJT_DEFAULT_BODY = """À Secretaria da {unit},

Prezados(as),

Meu nome é Hugo Mendes. Sou profissional cadastrado no Sistema AJ/JT da Justiça do Trabalho e atuo com cálculos trabalhistas, liquidação de sentença, conferência de cálculos e PJe-Calc.

Gostaria de apresentar minha disponibilidade para atuação como perito nesta unidade e, se cabível, solicitar minha vinculação à Vara para futuras nomeações, conforme os procedimentos aplicáveis.

Encaminho meu currículo pericial para apreciação.

Permaneço à disposição para quaisquer informações adicionais.

Atenciosamente,
Hugo Mendes
Perito cadastrado no Sistema AJ/JT
HM Perícia & Cálculos
E-mail: hugo@hmpericia.com.br
"""


AJT_INITIAL_UNITS = [
    {"tribunal":"TRT-15","city":"Ribeirão Preto","unit":"1ª Vara do Trabalho de Ribeirão Preto","email":"daarp.ribpreto@trt15.jus.br","address":"R. Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Ribeirão Preto","unit":"2ª Vara do Trabalho de Ribeirão Preto","email":"daarp.ribpreto@trt15.jus.br","address":"R. Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Ribeirão Preto","unit":"3ª Vara do Trabalho de Ribeirão Preto","email":"daarp.ribpreto@trt15.jus.br","address":"R. Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Ribeirão Preto","unit":"4ª Vara do Trabalho de Ribeirão Preto","email":"daarp.ribpreto@trt15.jus.br","address":"R. Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Ribeirão Preto","unit":"5ª Vara do Trabalho de Ribeirão Preto","email":"daarp.ribpreto@trt15.jus.br","address":"R. Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Ribeirão Preto","unit":"6ª Vara do Trabalho de Ribeirão Preto","email":"daarp.ribpreto@trt15.jus.br","address":"R. Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Sertãozinho","unit":"1ª Vara do Trabalho de Sertãozinho","email":"saj.1vt.sertaozinho@trt15.jus.br","address":"R. Antonio Seron, 254 - Centro - Sertãozinho/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Sertãozinho","unit":"2ª Vara do Trabalho de Sertãozinho","email":"saj.2vt.sertaozinho@trt15.jus.br","address":"R. Antonio Seron, 254 - Centro - Sertãozinho/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Franca","unit":"1ª Vara do Trabalho de Franca","email":"saj.1vt.franca@trt15.jus.br","address":"R. Frei Germano, 2310 - Estação - Franca/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Franca","unit":"2ª Vara do Trabalho de Franca","email":"saj.2vt.franca@trt15.jus.br","address":"R. Frei Germano, 2310 - Estação - Franca/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Araraquara","unit":"1ª Vara do Trabalho de Araraquara","email":"daaararaquara.scararaquara@trt15.jus.br","address":"Av. José Bonifácio, 176 - Centro - Araraquara/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Araraquara","unit":"2ª Vara do Trabalho de Araraquara","email":"daaararaquara.scararaquara@trt15.jus.br","address":"Av. José Bonifácio, 176 - Centro - Araraquara/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"Araraquara","unit":"3ª Vara do Trabalho de Araraquara","email":"daaararaquara.scararaquara@trt15.jus.br","address":"Av. José Bonifácio, 176 - Centro - Araraquara/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"São Carlos","unit":"1ª Vara do Trabalho de São Carlos","email":"saj.1vt.saocarlos@trt15.jus.br","address":"R. José Bonifácio, 888 - São Carlos/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
    {"tribunal":"TRT-15","city":"São Carlos","unit":"2ª Vara do Trabalho de São Carlos","email":"saj.2vt.saocarlos@trt15.jus.br","address":"R. José Bonifácio, 888 - São Carlos/SP","source_url":"https://trt15.jus.br/balcao-virtual-1grau"},
]

AJT_TRT15_CONTACT_GROUPS = [
    {
        "tribunal": "TRT-15",
        "city": "Araraquara",
        "unit": "Secretaria Conjunta TRT-15 — Araraquara",
        "email": "daaararaquara.scararaquara@trt15.jus.br",
        "address": "Avenida José Bonifácio, 176 - Araraquara/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Araraquara, Bebedouro, Cravinhos, Jaboticabal, Matão, Mococa, Pirassununga, Porto Ferreira, São Carlos, São José do Rio Pardo e Taquaritinga."
    },
    {
        "tribunal": "TRT-15",
        "city": "Bauru",
        "unit": "Secretaria Conjunta TRT-15 — Bauru",
        "email": "daabauru.scbauru@trt15.jus.br",
        "address": "Rua Xingu, 4-44 - Alto Higienópolis - Bauru/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Avaré, Bauru, Botucatu, Itápolis, Garça, Jaú, Lençóis Paulista, Marília, Ourinhos, Pederneiras e Santa Cruz do Rio Pardo."
    },
    {
        "tribunal": "TRT-15",
        "city": "Campinas",
        "unit": "Secretaria Conjunta TRT-15 — Campinas",
        "email": "daacampinas.sccampinas@trt15.jus.br",
        "address": "Avenida José de Souza Campos, 422 - Cambuí - Campinas/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Campinas, Mogi Mirim e Paulínia."
    },
    {
        "tribunal": "TRT-15",
        "city": "Jundiaí",
        "unit": "Secretaria Conjunta TRT-15 — Jundiaí",
        "email": "daajundiai.scjundiai@trt15.jus.br",
        "address": "Avenida Carlos Salles Block, 56 - Anhangabaú - Jundiaí/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Amparo, Atibaia, Bragança Paulista, Campo Limpo Paulista, Capivari, Indaiatuba, Itapira, Itatiba, Itu, Jundiaí e Salto."
    },
    {
        "tribunal": "TRT-15",
        "city": "Piracicaba",
        "unit": "Secretaria Conjunta TRT-15 — Piracicaba",
        "email": "daapiracicaba.scpiracicaba@trt15.jus.br",
        "address": "Rua João Pedro Corrêa, 810 - Piracicaba/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Americana, Araras, Hortolândia, Leme, Limeira, Mogi Guaçu, Piracicaba, Rio Claro, Santa Bárbara d'Oeste, São João da Boa Vista e Sumaré."
    },
    {
        "tribunal": "TRT-15",
        "city": "Presidente Prudente",
        "unit": "Secretaria Conjunta TRT-15 — Presidente Prudente",
        "email": "daapprudente.scpprudente@trt15.jus.br",
        "address": "Avenida Quatorze de Setembro, 1080 - Parque do Povo - Presidente Prudente/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Adamantina, Andradina, Araçatuba, Assis, Birigui, Dracena, Lins, Penápolis, Presidente Prudente, Presidente Venceslau, Teodoro Sampaio e Tupã."
    },
    {
        "tribunal": "TRT-15",
        "city": "Ribeirão Preto",
        "unit": "Secretaria Conjunta TRT-15 — Ribeirão Preto",
        "email": "daaribeiraopreto.scribeiraopreto@trt15.jus.br",
        "address": "Rua Afonso Taranto, 105 - Nova Ribeirania - Ribeirão Preto/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Batatais, Cajuru, Franca, Ituverava, Orlândia, Ribeirão Preto, São Joaquim da Barra e Sertãozinho."
    },
    {
        "tribunal": "TRT-15",
        "city": "São José do Rio Preto",
        "unit": "Secretaria Conjunta TRT-15 — São José do Rio Preto",
        "email": "daasjrp.scsjriopreto@trt15.jus.br",
        "address": "Avenida José Munia, 5500 - Chácara Municipal - São José do Rio Preto/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Barretos, Catanduva, Fernandópolis, Jales, José Bonifácio, Olímpia, São José do Rio Preto, Tanabi e Votuporanga."
    },
    {
        "tribunal": "TRT-15",
        "city": "São José dos Campos",
        "unit": "Secretaria Conjunta TRT-15 — São José dos Campos",
        "email": "daasjcampos.scsjcampos@trt15.jus.br",
        "address": "Rua Juiz David Barrilli, 85 - Parque Residencial Aquarius - São José dos Campos/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Aparecida, Caçapava, Caraguatatuba, Cruzeiro, Guaratinguetá, Jacareí, Lorena, Pindamonhangaba, São José dos Campos, São Sebastião, Taubaté e Ubatuba."
    },
    {
        "tribunal": "TRT-15",
        "city": "Sorocaba",
        "unit": "Secretaria Conjunta TRT-15 — Sorocaba",
        "email": "daasorocaba.scsorocaba@trt15.jus.br",
        "address": "Rua Ministro Coqueijo Costa, 61 - Alto da Boa Vista - Sorocaba/SP",
        "source_url": "https://trt15.jus.br/balcao-virtual-1grau",
        "notes": "Cobre as Varas de Capão Bonito, Itanhaém, Itapetininga, Itapeva, Itararé, Piedade, Registro, São Roque, Sorocaba, Tatuí e Tietê."
    },
]

SP_INTEREST_SCOPE = "Todos os municípios de SP informados no cadastro AJ/JT do usuário"

TRT15_SECRETARIAT_CITIES = {
    "Araraquara": ["Araraquara", "Bebedouro", "Cravinhos", "Jaboticabal", "Matão", "Mococa", "Pirassununga", "Porto Ferreira", "São Carlos", "São José do Rio Pardo", "Taquaritinga"],
    "Bauru": ["Avaré", "Bauru", "Botucatu", "Itápolis", "Garça", "Jaú", "Lençóis Paulista", "Marília", "Ourinhos", "Pederneiras", "Santa Cruz do Rio Pardo"],
    "Campinas": ["Campinas", "Mogi Mirim", "Paulínia"],
    "Jundiaí": ["Amparo", "Atibaia", "Bragança Paulista", "Campo Limpo Paulista", "Capivari", "Indaiatuba", "Itapira", "Itatiba", "Itu", "Jundiaí", "Salto"],
    "Piracicaba": ["Americana", "Araras", "Hortolândia", "Leme", "Limeira", "Mogi Guaçu", "Piracicaba", "Rio Claro", "Santa Bárbara D'Oeste", "São João da Boa Vista", "Sumaré"],
    "Presidente Prudente": ["Adamantina", "Andradina", "Araçatuba", "Assis", "Birigui", "Dracena", "Lins", "Penápolis", "Presidente Prudente", "Presidente Venceslau", "Teodoro Sampaio", "Tupã"],
    "Ribeirão Preto": ["Batatais", "Cajuru", "Franca", "Ituverava", "Orlândia", "Ribeirão Preto", "São Joaquim da Barra", "Sertãozinho"],
    "São José do Rio Preto": ["Barretos", "Catanduva", "Fernandópolis", "Jales", "José Bonifácio", "Olímpia", "São José do Rio Preto", "Tanabi", "Votuporanga"],
    "São José dos Campos": ["Aparecida", "Caçapava", "Caraguatatuba", "Cruzeiro", "Guaratinguetá", "Jacareí", "Lorena", "Pindamonhangaba", "São José dos Campos", "São Sebastião", "Taubaté", "Ubatuba"],
    "Sorocaba": ["Capão Bonito", "Itanhaém", "Itapetininga", "Itapeva", "Itararé", "Piedade", "Registro", "São Roque", "Sorocaba", "Tatuí", "Tietê"],
}

TRT15_MULTI_VARA_COUNTS = {
    "Americana": 2,
    "Araçatuba": 3,
    "Araraquara": 3,
    "Assis": 2,
    "Bauru": 4,
    "Campinas": 12,
    "Catanduva": 2,
    "Franca": 2,
    "Jaboticabal": 2,
    "Jacareí": 2,
    "Jaú": 2,
    "Jundiaí": 5,
    "Lençóis Paulista": 2,
    "Limeira": 2,
    "Marília": 2,
    "Paulínia": 2,
    "Piracicaba": 3,
    "Presidente Prudente": 2,
    "Ribeirão Preto": 6,
    "São Carlos": 2,
    "São José do Rio Preto": 4,
    "São José dos Campos": 5,
    "Sertãozinho": 2,
    "Sorocaba": 4,
    "Taubaté": 2,
}


TRT2_MUNICIPALITIES = [
    "Arujá", "Barueri", "Bertioga", "Biritiba Mirim", "Caieiras", "Cajamar",
    "Carapicuíba", "Cotia", "Cubatão", "Diadema", "Embu das Artes", "Embu-Guaçu",
    "Ferraz de Vasconcelos", "Francisco Morato", "Franco da Rocha", "Guararema",
    "Guarujá", "Guarulhos", "Ibiúna", "Itapecerica da Serra", "Itapevi",
    "Itaquaquecetuba", "Jandira", "Juquitiba", "Mairiporã", "Mauá",
    "Mogi das Cruzes", "Osasco", "Pirapora do Bom Jesus", "Poá", "Praia Grande",
    "Ribeirão Pires", "Rio Grande da Serra", "Salesópolis", "Santa Isabel",
    "Santana de Parnaíba", "Santo André", "Santos", "São Bernardo do Campo",
    "São Caetano do Sul", "São Lourenço da Serra", "São Paulo", "São Vicente",
    "Suzano", "Taboão da Serra", "Vargem Grande Paulista",
]

DEFAULT_SUBJECT = "Apoio técnico em cálculos trabalhistas"
DEFAULT_BODY = """Olá, equipe do {office}, tudo bem?

Meu nome é Hugo Mendes e sou responsável pela HM Perícia & Cálculos.

Vi que o escritório atua{profile_hint}. Prestamos apoio técnico terceirizado a advogados e escritórios na elaboração e conferência de cálculos trabalhistas, especialmente em PJe-Calc, liquidação de sentença, atualização de cálculos, conferência da conta da parte contrária e suporte técnico para impugnações.

A proposta é funcionar como uma retaguarda técnica do escritório: quando surgir uma demanda de cálculo, a equipe jurídica pode concentrar o tempo na condução do processo e deixar a etapa quantitativa conosco.

Caso atualmente terceirizem esse tipo de trabalho — ou tenham interesse em conhecer nosso modelo de parceria — posso encaminhar uma apresentação curta com os serviços e valores.

Atenciosamente,
Hugo Mendes
Diretor Técnico | Advogado | Perito Judicial
HM Perícia & Cálculos
WhatsApp: (31) 99587-1227
E-mail: hugo@hmpericia.com.br

Caso prefira não receber novos contatos da HM, basta nos avisar por este e-mail.
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


class AjtUnit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tribunal = db.Column(db.String(80), default="TRT-15", index=True)
    city = db.Column(db.String(120), index=True)
    unit = db.Column(db.String(260), nullable=False)
    email = db.Column(db.String(240), nullable=False, index=True)
    phone = db.Column(db.String(100))
    address = db.Column(db.String(500))
    source_url = db.Column(db.String(500))
    status = db.Column(db.String(80), default="Não contatado", index=True)
    last_contact = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AjtCurriculum(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120), nullable=False, default="application/pdf")
    data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AjtVaraLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tribunal = db.Column(db.String(80), default="TRT-15", index=True)
    secretariat = db.Column(db.String(120), nullable=False, index=True)
    contact_email = db.Column(db.String(240), nullable=False, index=True)
    city = db.Column(db.String(120), nullable=False, index=True)
    vara = db.Column(db.String(260), nullable=False, unique=True, index=True)
    status = db.Column(db.String(80), default="Não solicitado", index=True)
    requested_at = db.Column(db.DateTime(timezone=True))
    linked_at = db.Column(db.DateTime(timezone=True))
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AjtSendLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tribunal = db.Column(db.String(80), default="TRT-15", index=True)
    secretariat = db.Column(db.String(120), nullable=False, index=True)
    recipient = db.Column(db.String(240), nullable=False, index=True)
    subject = db.Column(db.String(300), nullable=False)
    result = db.Column(db.String(40), nullable=False, index=True)
    detail = db.Column(db.Text)
    sent_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


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


def resend_config_ready():
    return bool(
        os.environ.get("RESEND_API_KEY", "").strip()
        and os.environ.get("FROM_EMAIL", "").strip()
    )


def send_via_resend(recipient, subject, text_body, html_body, attachments=None):
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("FROM_EMAIL", "hugo@hmpericia.com.br").strip()
    reply_to = os.environ.get("REPLY_TO", from_email).strip()
    from_name = os.environ.get("FROM_NAME", "Hugo Mendes | HM Perícia & Cálculos").strip()

    if not api_key:
        raise RuntimeError("RESEND_API_KEY ainda não está configurada.")
    if not from_email:
        raise RuntimeError("FROM_EMAIL ainda não está configurado.")

    payload = {
        "from": f"{from_name} <{from_email}>",
        "to": [recipient],
        "subject": subject,
        "text": text_body,
        "html": html_body,
        "reply_to": reply_to,
    }

    if attachments:
        payload["attachments"] = [
            {
                "filename": item["filename"],
                "content": base64.b64encode(item["data"]).decode("ascii"),
            }
            for item in attachments
        ]

    req = urllib_request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "HM-Email-Disparador/1.0",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Resend retornou HTTP {response.status}.")
            return data
    except urllib_error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"Resend HTTP {exc.code}: {detail[:800]}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com a API da Resend: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Timeout ao conectar à API HTTPS da Resend.") from exc


def sent_today_count():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return SendLog.query.filter(SendLog.sent_at >= start, SendLog.result == "sent").count()


def ajt_sent_today_count(tribunal=None):
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    query = AjtSendLog.query.filter(
        AjtSendLog.sent_at >= start,
        AjtSendLog.result == "sent",
    )
    if tribunal:
        query = query.filter(AjtSendLog.tribunal == tribunal)
    return query.count()


def send_email_for_lead(lead):
    if not env_bool("SEND_ENABLED", False):
        raise RuntimeError("Envios estão bloqueados. Defina SEND_ENABLED=true no Railway somente após o teste Resend.")
    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")
    if lead.status == "Não contatar":
        raise RuntimeError("Lead marcado como Não contatar.")

    daily_limit = int(os.environ.get("DAILY_LIMIT", "20"))
    if sent_today_count() >= daily_limit:
        raise RuntimeError(f"Limite diário de {daily_limit} mensagens atingido.")

    subject = os.environ.get("EMAIL_SUBJECT", DEFAULT_SUBJECT)
    body = render_body(lead)
    html_body = (
        "<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;"
        "color:#14283d;background:#ffffff'>"
        "<div style='max-width:680px;margin:auto;padding:24px'>"
        "<div style='border-top:5px solid #c9a24a;padding-top:18px'>"
        + text_to_html(body)
        + "</div>"
        "<div style='margin-top:22px;padding-top:14px;border-top:1px solid #ddd;"
        "color:#667;font-size:12px'>"
        "HM Perícia &amp; Cálculos · Precisão técnica · Informações confiáveis · Decisões seguras"
        "</div></div></body></html>"
    )

    attachments = []
    if env_bool("ATTACH_MATERIAL", False):
        material = CampaignAttachment.query.order_by(CampaignAttachment.id.desc()).first()
        if material:
            attachments.append({"filename": material.filename, "data": material.data})

    provider_response = send_via_resend(
        recipient=lead.email,
        subject=subject,
        text_body=body,
        html_body=html_body,
        attachments=attachments,
    )

    provider_id = ""
    if isinstance(provider_response, dict):
        provider_id = str(provider_response.get("id") or "")

    lead.status = "Enviado"
    lead.last_contact = datetime.now(timezone.utc)
    lead.last_error = None
    db.session.add(SendLog(
        lead_id=lead.id,
        recipient=lead.email,
        subject=subject,
        result="sent",
        detail=((f"Resend ID: {provider_id}" if provider_id else "") + (" | retry_after_bounce" if allow_retry else "")).strip(" |") or None,
    ))
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


def import_ajt_rows(rows):
    imported = 0
    updated = 0
    skipped = 0

    for row in rows:
        unit = (row.get("Vara") or row.get("Unidade") or row.get("unit") or "").strip()
        email_addr = (row.get("E-mail") or row.get("Email") or row.get("email") or "").strip().lower()
        if not unit or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_addr):
            skipped += 1
            continue

        tribunal = (row.get("TRT") or row.get("Tribunal") or row.get("tribunal") or "TRT-15").strip()
        existing = AjtUnit.query.filter(
            db.func.lower(AjtUnit.email) == email_addr,
            AjtUnit.unit == unit,
        ).first()
        payload = {
            "tribunal": tribunal,
            "city": (row.get("Cidade") or row.get("city") or "").strip(),
            "unit": unit,
            "email": email_addr,
            "phone": (row.get("Telefone") or row.get("phone") or "").strip(),
            "address": (row.get("Endereço") or row.get("address") or "").strip(),
            "source_url": (row.get("Fonte") or row.get("Fonte pública") or row.get("source_url") or "").strip(),
            "notes": (row.get("Observações") or row.get("notes") or "").strip(),
        }
        if existing:
            for key, value in payload.items():
                if value:
                    setattr(existing, key, value)
            updated += 1
        else:
            db.session.add(AjtUnit(**payload, status="Não contatado"))
            imported += 1

    db.session.commit()
    return imported, updated, skipped


def render_ajt_body(unit):
    return AJT_DEFAULT_BODY.format(unit=unit.unit)


def seed_initial_ajt_units():
    seeded = 0
    for item in AJT_INITIAL_UNITS + AJT_TRT15_CONTACT_GROUPS:
        existing = AjtUnit.query.filter(
            AjtUnit.unit == item["unit"],
            db.func.lower(AjtUnit.email) == item["email"].lower(),
        ).first()
        if existing:
            for key, value in item.items():
                if value:
                    setattr(existing, key, value)
            continue
        db.session.add(AjtUnit(**item, status="Não contatado"))
        seeded += 1
    if seeded:
        db.session.commit()


def _trt15_contact_for(secretariat):
    for item in AJT_TRT15_CONTACT_GROUPS:
        if item["city"] == secretariat:
            return item["email"]
    return ""


def _vara_names_for_city(city):
    count = TRT15_MULTI_VARA_COUNTS.get(city, 1)
    if count == 1:
        return [f"Vara do Trabalho de {city}"]
    return [f"{number}ª Vara do Trabalho de {city}" for number in range(1, count + 1)]


def seed_trt15_vara_links():
    changed = False
    legacy_map = {
        "Vinculado": "Vinculado",
        "Vinculação solicitada": "Aguardando análise",
        "Apresentação enviada": "Solicitação enviada",
        "Acusou recebimento": "Aguardando análise",
    }
    for secretariat, cities in TRT15_SECRETARIAT_CITIES.items():
        contact_email = _trt15_contact_for(secretariat)
        for city in cities:
            for vara_name in _vara_names_for_city(city):
                existing = AjtVaraLink.query.filter_by(vara=vara_name).first()
                if existing:
                    existing.secretariat = secretariat
                    existing.contact_email = contact_email
                    existing.city = city
                    continue
                legacy = AjtUnit.query.filter_by(tribunal="TRT-15", unit=vara_name).first()
                status = legacy_map.get(legacy.status, "Não solicitado") if legacy else "Não solicitado"
                row = AjtVaraLink(
                    tribunal="TRT-15",
                    secretariat=secretariat,
                    contact_email=contact_email,
                    city=city,
                    vara=vara_name,
                    status=status,
                )
                if status in {"Solicitação enviada", "Aguardando análise", "Vinculado"}:
                    row.requested_at = legacy.last_contact if legacy else datetime.now(timezone.utc)
                if status == "Vinculado":
                    row.linked_at = legacy.last_contact if legacy else datetime.now(timezone.utc)
                db.session.add(row)
                changed = True
    if changed:
        db.session.commit()


def trt15_secretariat_overview():
    overview = []
    for secretariat in TRT15_SECRETARIAT_CITIES:
        rows = AjtVaraLink.query.filter_by(secretariat=secretariat).order_by(
            AjtVaraLink.city.asc(), AjtVaraLink.vara.asc()
        ).all()
        last_send = AjtSendLog.query.filter_by(
            tribunal="TRT-15",
            secretariat=secretariat,
            result="sent",
        ).order_by(AjtSendLog.sent_at.desc()).first()
        overview.append({
            "name": secretariat,
            "email": _trt15_contact_for(secretariat),
            "varas": rows,
            "total": len(rows),
            "linked": sum(1 for row in rows if row.status == "Vinculado"),
            "pending": sum(1 for row in rows if row.status in {"Solicitação enviada", "Aguardando análise"}),
            "not_requested": sum(1 for row in rows if row.status == "Não solicitado"),
            "last_send": last_send.sent_at if last_send else None,
        })
    return overview


def build_trt15_secretariat_message(secretariat):
    rows = AjtVaraLink.query.filter_by(secretariat=secretariat).filter(
        AjtVaraLink.status != "Não atuar"
    ).order_by(AjtVaraLink.city.asc(), AjtVaraLink.vara.asc()).all()
    subject = "Disponibilidade para futuras nomeações — perito calculista | SIGEO-JT/AJ-JT"
    body = f"""À Divisão de Atendimento e Administração da Secretaria Conjunta de {secretariat},

Prezados(as),

Meu nome é Hugo Mendes da Silva, advogado inscrito na OAB/SP nº 437.005 e OAB/MG nº 161.454, pós-graduado em Direito do Trabalho e perito calculista com cadastro nos sistemas oficiais da Justiça do Trabalho (SIGEO-JT/AJ-JT).

Atuo com cálculos trabalhistas e PJe-Calc, incluindo liquidação de sentença, atualização de créditos, conferência de cálculos e apoio técnico em impugnações.

Escrevo apenas para registrar minha disponibilidade para futuras nomeações como perito calculista nas unidades atendidas por essa Secretaria Conjunta, caso haja necessidade e conforme os critérios do Juízo.

Meu currículo pericial segue anexo apenas para referência, sem necessidade de qualquer providência ou resposta a este e-mail.

Permaneço à disposição.

Atenciosamente,

Hugo Mendes da Silva
Perito calculista | SIGEO-JT/AJ-JT
OAB/SP 437.005 | OAB/MG 161.454
HM Perícia & Cálculos
hugo@hmpericia.com.br
(31) 99587-1227
"""
    return subject, body, rows


def send_trt15_secretariat_email(secretariat, allow_retry=False):
    if secretariat not in TRT15_SECRETARIAT_CITIES:
        raise RuntimeError("Secretaria Conjunta inválida.")
    if not env_bool("AJT_SEND_ENABLED", False):
        raise RuntimeError("Envios AJ/JT estão bloqueados. Ative AJT_SEND_ENABLED somente após revisar currículo e mensagem.")
    if not resend_config_ready():
        raise RuntimeError("RESEND_API_KEY/FROM_EMAIL ainda não estão configurados.")

    curriculum = AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first()
    if not curriculum:
        raise RuntimeError("Currículo pericial não cadastrado no módulo AJ/JT.")

    recipient = _trt15_contact_for(secretariat)
    if not recipient or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", recipient):
        raise RuntimeError("E-mail institucional da Secretaria não está válido.")

    previous = AjtSendLog.query.filter_by(
        tribunal="TRT-15",
        secretariat=secretariat,
        recipient=recipient,
        result="sent",
    ).first()
    if previous and not allow_retry:
        raise RuntimeError(
            f"Já existe envio concluído para esta Secretaria em {previous.sent_at.strftime('%d/%m/%Y')}. "
            "O sistema bloqueia duplicidade; eventual reenvio deve ser tratado como follow-up."
        )

    daily_limit = max(
        1,
        int(os.environ.get("AJT_TRT15_DAILY_LIMIT", os.environ.get("AJT_DAILY_LIMIT", "3"))),
    )
    if ajt_sent_today_count("TRT-15") >= daily_limit:
        raise RuntimeError(f"Limite TRT-15 diário de {daily_limit} Secretaria(s) atingido.")

    subject, body, rows = build_trt15_secretariat_message(secretariat)
    html_body = (
        "<!doctype html><html><body style='font-family:Arial,Helvetica,sans-serif;color:#222;background:#fff'>"
        "<div style='max-width:720px;margin:auto;padding:20px'>"
        + text_to_html(body)
        + "</div></body></html>"
    )

    provider_response = None
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
            tribunal="TRT-15",
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
            row.status = "Apresentação enviada"
        if not row.requested_at:
            row.requested_at = now
        row.updated_at = now

    contact = AjtUnit.query.filter(
        AjtUnit.tribunal == "TRT-15",
        AjtUnit.unit == f"Secretaria Conjunta TRT-15 — {secretariat}",
    ).first()
    if contact:
        contact.status = "Apresentação enviada"
        contact.last_contact = now

    provider_id = ""
    if isinstance(provider_response, dict):
        provider_id = str(provider_response.get("id") or "")

    db.session.add(AjtSendLog(
        tribunal="TRT-15",
        secretariat=secretariat,
        recipient=recipient,
        subject=subject,
        result="sent",
        detail=(f"Resend ID: {provider_id}" if provider_id else None),
    ))
    db.session.commit()
    return recipient, len(rows)


@app.get("/historico-envios")
@login_required
def send_history():
    kind = request.args.get("tipo", "").strip()
    status_filter = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip().lower()
    local_tz = ZoneInfo("America/Sao_Paulo")
    entries = []

    if kind in {"", "comercial"}:
        for log in SendLog.query.order_by(SendLog.sent_at.desc()).limit(500).all():
            lead = log.lead
            entries.append({
                "type": "comercial",
                "type_label": "Prospecção HM",
                "source": lead.office if lead else "Lead comercial",
                "recipient": log.recipient,
                "subject": log.subject,
                "result": log.result,
                "detail": log.detail or "",
                "sent_at": log.sent_at,
                "sent_at_local": log.sent_at.astimezone(local_tz) if log.sent_at else None,
                "tribunal": "",
                "secretariat": "",
            })

    if kind in {"", "ajt"}:
        for log in AjtSendLog.query.order_by(AjtSendLog.sent_at.desc()).limit(500).all():
            entries.append({
                "type": "ajt",
                "type_label": "AJ/JT",
                "source": f"{log.tribunal} · {log.secretariat}",
                "recipient": log.recipient,
                "subject": log.subject,
                "result": log.result,
                "detail": log.detail or "",
                "sent_at": log.sent_at,
                "sent_at_local": log.sent_at.astimezone(local_tz) if log.sent_at else None,
                "tribunal": log.tribunal,
                "secretariat": log.secretariat,
            })

    if status_filter:
        entries = [row for row in entries if row["result"] == status_filter]

    if search:
        entries = [
            row for row in entries
            if search in " ".join([
                row["source"],
                row["recipient"],
                row["subject"],
                row["detail"],
                row["tribunal"],
                row["secretariat"],
            ]).lower()
        ]

    entries.sort(
        key=lambda row: row["sent_at"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    total_sent = SendLog.query.filter_by(result="sent").count() + AjtSendLog.query.filter_by(result="sent").count()
    total_errors = SendLog.query.filter_by(result="error").count() + AjtSendLog.query.filter_by(result="error").count()
    commercial_sent = SendLog.query.filter_by(result="sent").count()
    ajt_sent = AjtSendLog.query.filter_by(result="sent").count()

    return render_template(
        "send_history.html",
        entries=entries[:500],
        total_sent=total_sent,
        total_errors=total_errors,
        commercial_sent=commercial_sent,
        ajt_sent=ajt_sent,
    )


@app.get("/health")
def health():
    return {"ok": True, "service": "hm-email-disparador"}, 200


bh_internal_batch_state = {"running": False, "started_at": None}


@app.get("/internal/ajt/trt3/bh/start")
def internal_ajt_trt3_bh_start():
    expected = os.environ.get("AJT_INTERNAL_TRIGGER_TOKEN", "").strip()
    supplied = request.args.get("token", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        return {"ok": False, "error": "unauthorized"}, 403

    if bh_internal_batch_state["running"]:
        return {"ok": True, "started": False, "reason": "already_running"}, 200

    def worker():
        bh_internal_batch_state["running"] = True
        bh_internal_batch_state["started_at"] = datetime.now(timezone.utc).isoformat()
        try:
            from trt3_bh_batch import main as run_bh_batch
            run_bh_batch()
        except Exception:
            app.logger.exception("Falha no lote interno AJ/JT TRT-3 BH")
        finally:
            bh_internal_batch_state["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return {
        "ok": True,
        "started": True,
        "scope": "TRT-3 Belo Horizonte — 48 Varas",
    }, 202


@app.get("/internal/ajt/trt3/bh/status")
def internal_ajt_trt3_bh_status():
    expected = os.environ.get("AJT_INTERNAL_TRIGGER_TOKEN", "").strip()
    supplied = request.args.get("token", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        return {"ok": False, "error": "unauthorized"}, 403

    return {
        "ok": True,
        "running": bh_internal_batch_state["running"],
        "started_at": bh_internal_batch_state["started_at"],
    }, 200


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
        resend_ready=resend_config_ready(),
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


@app.route("/ajt", methods=["GET", "POST"])
@login_required
def ajt_units():
    if request.method == "POST":
        action = request.form.get("action", "import")
        if action == "add":
            unit_name = request.form.get("unit", "").strip()
            email_addr = request.form.get("email", "").strip().lower()
            if not unit_name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_addr):
                flash("Informe a unidade e um e-mail válido.", "danger")
            else:
                existing = AjtUnit.query.filter(
                    db.func.lower(AjtUnit.email) == email_addr,
                    AjtUnit.unit == unit_name,
                ).first()
                if existing:
                    flash("Essa unidade já está cadastrada com esse e-mail.", "warning")
                else:
                    db.session.add(AjtUnit(
                        tribunal=request.form.get("tribunal", "TRT-15").strip() or "TRT-15",
                        city=request.form.get("city", "").strip(),
                        unit=unit_name,
                        email=email_addr,
                        phone=request.form.get("phone", "").strip(),
                        address=request.form.get("address", "").strip(),
                        source_url=request.form.get("source_url", "").strip(),
                        notes=request.form.get("notes", "").strip(),
                    ))
                    db.session.commit()
                    flash("Unidade AJ/JT cadastrada.", "success")
            return redirect(url_for("ajt_units"))

        file = request.files.get("file")
        if not file or not file.filename:
            flash("Selecione um CSV de unidades.", "warning")
        elif not file.filename.lower().endswith(".csv"):
            flash("A importação aceita arquivo CSV.", "danger")
        else:
            try:
                raw = file.read().decode("utf-8-sig")
                imported, updated, skipped = import_ajt_rows(csv.DictReader(io.StringIO(raw)))
                flash(
                    f"Base AJ/JT atualizada: {imported} nova(s), {updated} atualizada(s), {skipped} ignorada(s).",
                    "success",
                )
            except Exception as exc:
                flash(f"Falha na importação AJ/JT: {exc}", "danger")
        return redirect(url_for("ajt_units"))

    q = AjtUnit.query
    status = request.args.get("status", "")
    tribunal = request.args.get("tribunal", "")
    city = request.args.get("city", "")
    search = request.args.get("q", "").strip()
    if status:
        q = q.filter(AjtUnit.status == status)
    if tribunal:
        q = q.filter(AjtUnit.tribunal == tribunal)
    if city:
        q = q.filter(AjtUnit.city == city)
    if search:
        term = f"%{search}%"
        q = q.filter(db.or_(AjtUnit.unit.ilike(term), AjtUnit.city.ilike(term), AjtUnit.email.ilike(term)))

    rows = q.order_by(AjtUnit.tribunal.asc(), AjtUnit.city.asc(), AjtUnit.unit.asc()).all()
    tribunals = [r[0] for r in db.session.query(AjtUnit.tribunal).distinct().order_by(AjtUnit.tribunal).all() if r[0]]
    cities = [r[0] for r in db.session.query(AjtUnit.city).distinct().order_by(AjtUnit.city).all() if r[0]]
    curriculum = AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first()
    return render_template(
        "ajt.html",
        units=rows,
        status_options=AJT_STATUS_OPTIONS,
        tribunals=tribunals,
        cities=cities,
        curriculum=curriculum,
        total=AjtUnit.query.count(),
        pending=AjtUnit.query.filter_by(status="Não contatado").count(),
        linked=AjtUnit.query.filter_by(status="Vinculado").count(),
        unique_contacts=db.session.query(db.func.lower(AjtUnit.email)).filter(AjtUnit.email != "").distinct().count(),
        trt15_groups=AjtUnit.query.filter(
            AjtUnit.tribunal == "TRT-15",
            AjtUnit.unit.like("Secretaria Conjunta TRT-15%")
        ).count(),
        sp_interest_scope=SP_INTEREST_SCOPE,
        trt2_municipalities=TRT2_MUNICIPALITIES,
        trt2_count=len(TRT2_MUNICIPALITIES),
    )


@app.get("/ajt/trt15")
@login_required
def ajt_trt15_links():
    secretariats = trt15_secretariat_overview()
    total_varas = AjtVaraLink.query.filter_by(tribunal="TRT-15").count()
    linked_varas = AjtVaraLink.query.filter_by(tribunal="TRT-15", status="Vinculado").count()
    requested_varas = AjtVaraLink.query.filter(
        AjtVaraLink.tribunal == "TRT-15",
        AjtVaraLink.status.in_(["Solicitação enviada", "Aguardando análise", "Vinculado", "Não vinculado"]),
    ).count()
    return render_template(
        "ajt_trt15.html",
        secretariats=secretariats,
        status_options=AJT_VARA_STATUS_OPTIONS,
        total_varas=total_varas,
        linked_varas=linked_varas,
        requested_varas=requested_varas,
    )


@app.post("/ajt/trt15/vara/<int:vara_id>/status")
@login_required
def ajt_trt15_update_vara(vara_id):
    vara = db.get_or_404(AjtVaraLink, vara_id)
    new_status = request.form.get("status", "")
    if new_status in AJT_VARA_STATUS_OPTIONS:
        old_status = vara.status
        vara.status = new_status
        vara.updated_at = datetime.now(timezone.utc)
        if new_status in {"Solicitação enviada", "Aguardando análise", "Vinculado", "Não vinculado"} and not vara.requested_at:
            vara.requested_at = datetime.now(timezone.utc)
        if new_status == "Vinculado" and not vara.linked_at:
            vara.linked_at = datetime.now(timezone.utc)
        elif old_status == "Vinculado" and new_status != "Vinculado":
            vara.linked_at = None
        db.session.commit()
        flash(f"Status atualizado: {vara.vara}.", "success")
    return redirect(request.referrer or url_for("ajt_trt15_links"))


@app.post("/ajt/trt15/secretaria/<secretariat>/marcar-enviado")
@login_required
def ajt_trt15_mark_sent(secretariat):
    rows = AjtVaraLink.query.filter_by(secretariat=secretariat, status="Não solicitado").all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "Solicitação enviada"
        row.requested_at = now
        row.updated_at = now
    db.session.commit()
    flash(f"Solicitação registrada para {len(rows)} Vara(s) da Secretaria Conjunta de {secretariat}.", "success")
    return redirect(url_for("ajt_trt15_links") + f"#sec-{secretariat}")


@app.get("/ajt/trt15/secretaria/<secretariat>/preview")
@login_required
def ajt_trt15_secretariat_preview(secretariat):
    if secretariat not in TRT15_SECRETARIAT_CITIES:
        return "Secretaria não encontrada.", 404
    subject, body, rows = build_trt15_secretariat_message(secretariat)
    contact_email = _trt15_contact_for(secretariat)
    previous = AjtSendLog.query.filter_by(
        tribunal="TRT-15",
        secretariat=secretariat,
        recipient=contact_email,
        result="sent",
    ).order_by(AjtSendLog.sent_at.desc()).first()
    return render_template(
        "ajt_secretariat_preview.html",
        secretariat=secretariat,
        contact_email=contact_email,
        subject=subject,
        body=body,
        varas=rows,
        curriculum=AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first(),
        send_enabled=env_bool("AJT_SEND_ENABLED", False),
        sent_today=ajt_sent_today_count(),
        daily_limit=max(1, int(os.environ.get("AJT_DAILY_LIMIT", "2"))),
        previous=previous,
    )


@app.post("/ajt/trt15/secretaria/<secretariat>/send")
@login_required
def ajt_trt15_send_secretariat(secretariat):
    try:
        recipient, total_varas = send_trt15_secretariat_email(secretariat)
        flash(
            f"E-mail institucional enviado para {recipient}. "
            f"{total_varas} Vara(s) ficaram registradas como solicitação enviada.",
            "success",
        )
    except Exception as exc:
        flash(f"Envio AJ/JT não realizado: {exc}", "danger")
    return redirect(url_for("ajt_trt15_secretariat_preview", secretariat=secretariat))


@app.post("/ajt/<int:unit_id>/status")
@login_required
def ajt_update_status(unit_id):
    unit = db.get_or_404(AjtUnit, unit_id)
    new_status = request.form.get("status", "")
    if new_status in AJT_STATUS_OPTIONS:
        unit.status = new_status
        if new_status in {"Apresentação enviada", "Acusou recebimento", "Vinculação solicitada", "Vinculado"}:
            unit.last_contact = datetime.now(timezone.utc)
        db.session.commit()
        flash("Status AJ/JT atualizado.", "success")
    return redirect(request.referrer or url_for("ajt_units"))


@app.get("/ajt/<int:unit_id>/preview")
@login_required
def ajt_preview(unit_id):
    unit = db.get_or_404(AjtUnit, unit_id)
    return render_template(
        "ajt_preview.html",
        unit=unit,
        subject=AJT_DEFAULT_SUBJECT,
        body=render_ajt_body(unit),
        curriculum=AjtCurriculum.query.order_by(AjtCurriculum.id.desc()).first(),
    )


@app.route("/ajt/curriculo", methods=["POST"])
@login_required
def ajt_curriculum():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Selecione o currículo pericial em PDF.", "warning")
    elif not file.filename.lower().endswith(".pdf"):
        flash("O currículo AJ/JT deve ser enviado em PDF.", "danger")
    else:
        data = file.read()
        if len(data) > 5 * 1024 * 1024:
            flash("O currículo deve ter no máximo 5 MB.", "danger")
        else:
            AjtCurriculum.query.delete()
            db.session.add(AjtCurriculum(
                filename=file.filename.strip(),
                mimetype="application/pdf",
                data=data,
            ))
            db.session.commit()
            flash("Currículo pericial AJ/JT salvo separadamente do material comercial.", "success")
    return redirect(url_for("ajt_units"))


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
        elif not resend_config_ready():
            flash("Configure RESEND_API_KEY e FROM_EMAIL no Railway primeiro.", "danger")
        else:
            try:
                test_text = "Teste concluído com sucesso. O disparador da HM está enviando pela API HTTPS da Resend."
                send_via_resend(
                    recipient=recipient,
                    subject="Teste Resend — HM Perícia & Cálculos",
                    text_body=test_text,
                    html_body=f"<p>{html.escape(test_text)}</p>",
                )
                flash("Teste enviado com sucesso pela Resend.", "success")
            except Exception as exc:
                flash(f"Falha no teste Resend: {exc}", "danger")

    return render_template(
        "test_email.html",
        resend_ready=resend_config_ready(),
        send_enabled=env_bool("SEND_ENABLED", False),
    )


with app.app_context():
    db.create_all()
    seed_initial_ajt_units()
    seed_trt15_vara_links()
    seed_b64 = os.environ.get("LEADS_SEED_B64", "").strip()
    if seed_b64 and Lead.query.count() == 0:
        try:
            seed_csv = base64.b64decode(seed_b64).decode("utf-8-sig")
            import_lead_rows(csv.DictReader(io.StringIO(seed_csv)))
        except Exception as exc:
            app.logger.error("Falha ao carregar base inicial de leads: %s", exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
