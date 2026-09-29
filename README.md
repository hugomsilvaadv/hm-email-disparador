# Street Mall Intelligence — Originação & Prospecção

Versão especializada do painel de prospecção, mantida na branch \`street-mall-crm\` para não interferir no disparador da HM.

## Escopo inicial
- importar a planilha existente em XLSX pela aba **Pipeline Terrenos**;
- consolidar imóveis em fichas individuais;
- enriquecer testada, zoneamento, matrícula, proprietário, acessos, infraestrutura e geolocalização;
- cadastrar múltiplos contatos por imóvel;
- registrar interações e follow-ups;
- filtrar por praça, prioridade, status e disponibilidade;
- preparar e-mails individualmente;
- enviar via Resend somente quando **SEND_ENABLED=true**.

## Variáveis Railway
- \`ADMIN_USER\`
- \`ADMIN_PASSWORD\`
- \`SECRET_KEY\`
- \`DATABASE_URL\`
- \`RESEND_API_KEY\` (quando a prospecção for liberada)
- \`FROM_EMAIL\`
- \`REPLY_TO\`
- \`FROM_NAME\`
- \`SEND_ENABLED=false\` inicialmente

## Segurança
O módulo de e-mail nasce bloqueado. A base e a pesquisa funcionam normalmente sem configurar remetente ou liberar disparos.
