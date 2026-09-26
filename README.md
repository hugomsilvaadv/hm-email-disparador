# HM Perícia & Cálculos — Disparador B2B

Painel privado para prospecção de escritórios usando `hugo@hmpericia.com.br` via SMTP Titan.

## Segurança
- Nenhuma senha fica no GitHub.
- SMTP e senha administrativa ficam apenas nas variáveis do Railway.
- `SEND_ENABLED=false` por padrão.
- Envios individuais, com limite diário e intervalo mínimo.
- A base de leads e o histórico ficam no PostgreSQL do Railway.

## Railway
Variáveis esperadas: `ADMIN_USER`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `FROM_NAME`, `DAILY_LIMIT`, `MIN_INTERVAL_SECONDS`, `SEND_ENABLED` e `DATABASE_URL`.

Antes de liberar a campanha, use a tela **Teste SMTP** e envie apenas para um endereço seu.