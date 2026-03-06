# HOWTO Completo: Implementação e Uso do LGM Monitoring Agent

Este guia cobre implementação, hardening, compilação, empacotamento, instalação, operação e troubleshooting do ecossistema:

- `Agent`: coleta e envia métricas via push (`agent/lgm_agent.py`)
- `Receiver`: recebe e integra com Centreon (`receiver/lgm_receiver.py`)
- `Plugin Centreon`: consulta `/metrics` e retorna status Nagios (`centreon-plugin/check_lgm_metrics.py`)

## 1) Visão Geral da Arquitetura

Fluxo:

1. Servidor monitorado executa `lgm-agent`.
2. Agent envia `POST /register` (primeira execução) e `POST /ingest` periodicamente.
3. Receiver valida token + HMAC (opcional/recomendado), armazena no SQLite.
4. Receiver integra host com Centreon (API/CLI).
5. Plugin Centreon consulta `GET /metrics?host=...` e publica status/perfdata.

Características:

- Outbound-only no host monitorado.
- Sem porta de escuta no servidor monitorado.
- Transporte HTTPS.
- Token criptografado localmente (Fernet).
- HMAC com proteção anti-replay (`timestamp` + `nonce`).
- Anti-replay persistido em SQLite (sem serviços externos).

## 2) Pré-requisitos

### 2.1 Host do Receiver

- Linux x86_64.
- Python 3.10+ (recomendado 3.11/3.12).
- Acesso ao Centreon (API e/ou CLI).
- Porta HTTPS aberta para receber agents.

### 2.2 Hosts monitorados (Agent)

- Linux x86_64.
- Python 3.10+ (se rodar script), ou binário standalone compilado.
- Saída HTTPS liberada para o Receiver.

## 3) Estrutura dos Arquivos no Projeto

- `agent/lgm_agent.py`
- `receiver/lgm_receiver.py`
- `centreon-plugin/check_lgm_metrics.py`
- `examples/agent.config.json`
- `examples/receiver.config.json`
- `deploy/systemd/lgm-agent.service`
- `deploy/systemd/lgm-receiver.service`
- `scripts/encrypt_token.py`
- `scripts/build_linux.sh`
- `.github/workflows/build-linux-packages.yml`

## 4) Implantação do Receiver (Passo a Passo)

### 4.1 Preparar diretórios

```bash
sudo mkdir -p /etc/lgm-monitor /var/lib/lgm-monitor /var/log/lgm-monitor
sudo chmod 700 /etc/lgm-monitor
```

### 4.2 Criar configuração base

```bash
sudo cp examples/receiver.config.json /etc/lgm-monitor/config.json
sudo chmod 600 /etc/lgm-monitor/config.json
```

Campos críticos:

- `receiver_bind_address`, `receiver_port`
- `db_path`
- `agent_tokens` ou `agent_token_file`/`agent_key_file`
- `hmac_enabled` e parâmetros de HMAC
- parâmetros Centreon (`centreon_*`)

### 4.3 Criar token do Agent (criptografado)

Opção recomendada: um token compartilhado entre agentes do mesmo ambiente.

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-monitor/agent_key.bin \
  --token-file /etc/lgm-monitor/agent_token.enc \
  --token 'TOKEN_AGENT_PRODUCAO'

sudo chmod 600 /etc/lgm-monitor/agent_key.bin /etc/lgm-monitor/agent_token.enc
```

### 4.4 Criar segredo HMAC (criptografado)

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-monitor/hmac_key.bin \
  --token-file /etc/lgm-monitor/hmac_secret.enc \
  --token 'SEGREDO_HMAC_COMPARTILHADO'

sudo chmod 600 /etc/lgm-monitor/hmac_key.bin /etc/lgm-monitor/hmac_secret.enc
```

### 4.5 (Opcional) Token da API Centreon criptografado

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-monitor/key.bin \
  --token-file /etc/lgm-monitor/centreon_token.enc \
  --token 'CENTREON_API_TOKEN'

sudo chmod 600 /etc/lgm-monitor/key.bin /etc/lgm-monitor/centreon_token.enc
```

### 4.6 Executar Receiver

Modo script:

```bash
python3 receiver/lgm_receiver.py --config /etc/lgm-monitor/config.json
```

Modo serviço systemd:

```bash
sudo cp deploy/systemd/lgm-receiver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lgm-receiver
sudo systemctl status lgm-receiver
```

## 5) Implantação do Agent (Passo a Passo)

### 5.1 Preparar diretórios

```bash
sudo mkdir -p /etc/lgm-agent /var/log/lgm-agent
sudo chmod 700 /etc/lgm-agent
```

### 5.2 Configuração

```bash
sudo cp examples/agent.config.json /etc/lgm-agent/config.json
sudo chmod 600 /etc/lgm-agent/config.json
```

Ajustar:

- `receiver_url`
- `update_url`
- `collection_interval`
- `verify_tls`
- `plugin` (`linux` inicialmente)

### 5.3 Token criptografado do Agent

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-agent/key.bin \
  --token-file /etc/lgm-agent/token.enc \
  --token 'TOKEN_AGENT_PRODUCAO'

sudo chmod 600 /etc/lgm-agent/key.bin /etc/lgm-agent/token.enc
```

### 5.4 Segredo HMAC no Agent

Deve ser o mesmo valor usado no Receiver.

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-agent/hmac_key.bin \
  --token-file /etc/lgm-agent/hmac_secret.enc \
  --token 'SEGREDO_HMAC_COMPARTILHADO'

sudo chmod 600 /etc/lgm-agent/hmac_key.bin /etc/lgm-agent/hmac_secret.enc
```

### 5.5 Executar Agent

Modo script:

```bash
python3 agent/lgm_agent.py --config /etc/lgm-agent/config.json
```

Modo systemd:

```bash
sudo cp deploy/systemd/lgm-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lgm-agent
sudo systemctl status lgm-agent
```

## 6) HMAC, Anti-Replay e Segurança

### 6.1 Cabeçalhos HMAC

Quando `hmac_enabled=true`, o Agent envia:

- `X-Signature`
- `X-Signature-Timestamp`
- `X-Signature-Nonce`

### 6.2 Validação no Receiver

Receiver valida:

- token (`Authorization`/`X-Agent-Token`)
- janela de tempo (`hmac_max_skew_seconds`)
- unicidade de nonce (SQLite table `hmac_nonces`)
- assinatura HMAC (`method + path + timestamp + nonce + sha256(body)`)

### 6.3 Hardening recomendado

- `verify_tls=true` sempre em produção.
- Certificado TLS válido no Receiver.
- Permissão `600` para `*.enc` e `*.bin`.
- Rotação periódica de token/HMAC (com rollout controlado).
- Definir `max_request_size_bytes` conservador (ex.: 256KB).

## 7) Banco SQLite (Operação)

O Receiver usa SQLite para:

- `registrations`: hosts registrados
- `metrics`: último payload por host
- `hmac_nonces`: proteção anti-replay

Manutenção automática configurável:

- `nonce_cleanup_interval_seconds`
- `sqlite_vacuum_interval_seconds`

Boas práticas:

- `db_path` em disco persistente.
- backup periódico do arquivo `.db`.
- monitorar tamanho de arquivo.

## 8) Integração com Centreon

No `POST /register`, se host novo:

1. `create_host`
2. `apply_template`
3. `assign_hostgroup`
4. `export_configuration`

A implementação tenta API REST e faz fallback CLI.

Parâmetros mínimos:

- `centreon_api_url` (se usar API)
- `centreon_username`/`centreon_password` (fallback CLI e/ou auth)
- `centreon_default_template`
- `centreon_hostgroup`
- `centreon_poller_name`

## 9) Plugin Centreon (Check)

Exemplo de execução:

```bash
python3 centreon-plugin/check_lgm_metrics.py \
  --url https://receiver.seu-dominio:8443 \
  --token TOKEN_AGENT_PRODUCAO \
  --host srv-app-01
```

Retorno esperado:

```text
OK - cpu 12.0% mem 30.0% disk 40.0% | cpu=12.0;80;90;0;100 mem=30.0;80;90;0;100 disk=40.0;80;90;0;100
```

## 10) Auto-Update do Agent

Fluxo:

1. Agent consulta `GET /agent/version`.
2. Compara versão local/remota.
3. Se nova versão: baixa binário, valida SHA256.
4. Substitui executável e reinicia.

Requisitos:

- `latest_agent_version`
- `latest_agent_download_url`
- `latest_agent_sha256`

Prática recomendada:

- publicar binário em URL HTTPS estável.
- atualizar SHA256 junto com versão.
- testar em ambiente de staging antes de produção.

## 11) Compilação Standalone

### 11.1 PyInstaller (manual)

```bash
pyinstaller --noconfirm --clean --onefile --name lgm-agent agent/lgm_agent.py
pyinstaller --noconfirm --clean --onefile --name lgm-receiver receiver/lgm_receiver.py
```

### 11.2 Pacotes Linux (.deb e .rpm)

```bash
chmod +x scripts/build_linux.sh
scripts/build_linux.sh 1.0.0 artifacts        # deb + rpm
scripts/build_linux.sh 1.0.0 artifacts deb    # só deb
scripts/build_linux.sh 1.0.0 artifacts rpm    # só rpm
```

## 12) CI/CD de Pacotes e Release

Workflow:

- `.github/workflows/build-linux-packages.yml`

Acionamento:

- manual (`workflow_dispatch`)
- automático por tag `v*`

Saídas:

- artifacts `deb-packages` e `rpm-packages`
- checksums `SHA256SUMS-deb.txt`, `SHA256SUMS-rpm.txt`, `SHA256SUMS.txt`
- publicação automática em GitHub Release (tags `v*`)

## 13) Runbook de Verificação Rápida

### 13.1 Saúde do Receiver

```bash
systemctl status lgm-receiver
journalctl -u lgm-receiver -n 100 --no-pager
```

### 13.2 Saúde do Agent

```bash
systemctl status lgm-agent
journalctl -u lgm-agent -n 100 --no-pager
```

### 13.3 Teste API Receiver

```bash
curl -k -H "X-Agent-Token: TOKEN_AGENT_PRODUCAO" "https://receiver:8443/metrics?host=srv-app-01"
```

## 14) Troubleshooting

### 14.1 `401 Unauthorized token`

- Token diferente entre Agent e Receiver.
- `token.enc`/`key.bin` incorretos no host.

### 14.2 `401 Invalid HMAC signature`

- Segredo HMAC divergente.
- Corpo assinado diferente do corpo recebido.
- Proxy/reverse proxy alterando request.

### 14.3 `401 Expired HMAC timestamp`

- Relógio fora de sincronia.
- Ajustar NTP/chrony.
- Revisar `hmac_max_skew_seconds`.

### 14.4 `401 Replay detected`

- Requisição repetida com mesmo nonce.
- Retentativas indevidas no caminho de rede.

### 14.5 Centreon host não criado

- Credenciais/API inválidas.
- Endpoint API bloqueado.
- CLI Centreon indisponível no receiver.

### 14.6 Sem dados no `/metrics`

- Agent não conseguiu `POST /ingest`.
- Verificar conectividade/TLS/token/HMAC.
- Ver logs do agent e receiver.

## 15) Recomendações de Produção

- Separar ambientes (`dev`, `staging`, `prod`) com tokens/HMAC distintos.
- Certificados TLS válidos e renovação automatizada.
- Rodar receiver atrás de reverse proxy com rate limiting.
- Criar backup diário do SQLite e retenção de 7-30 dias.
- Versionar configuração com controle seguro (sem segredos em plaintext).
- Validar cada release em staging antes de promover.

## 16) Checklist Final de Go-Live

- [ ] Receiver ativo e respondendo HTTPS.
- [ ] Agent registrando e enviando métricas.
- [ ] Token e HMAC criptografados e com permissões corretas.
- [ ] Endpoint `/metrics` retornando dados do host.
- [ ] Host criado no Centreon com template/hostgroup corretos.
- [ ] Plugin Centreon retornando `OK/WARNING/CRITICAL` corretamente.
- [ ] Auto-update testado em ambiente controlado.
- [ ] Build `.deb`/`.rpm` e checksums publicados.

---

Se quiser, o próximo passo é eu gerar também um runbook operacional separado por perfil (NOC, SRE e Segurança) com playbooks de incidente e rotação de segredo sem downtime.

## 17) Automacao de Instalacao

### 17.1 Bootstrap por script

Scripts disponiveis:
- `scripts/bootstrap_agent.sh`
- `scripts/bootstrap_receiver.sh`

Exemplos:

```bash
sudo bash scripts/bootstrap_agent.sh dist/lgm-agent
sudo bash scripts/bootstrap_receiver.sh dist/lgm-receiver
```

Com start automatico:

```bash
sudo bash scripts/bootstrap_agent.sh dist/lgm-agent start
sudo bash scripts/bootstrap_receiver.sh dist/lgm-receiver start
```

### 17.2 Hooks de pacote (DEB/RPM)

Hooks implementados:
- `packaging/hooks/agent/post-install.sh`
- `packaging/hooks/agent/before-remove.sh`
- `packaging/hooks/receiver/post-install.sh`
- `packaging/hooks/receiver/before-remove.sh`

Comportamento:
- `post-install`: prepara diretorios, coloca config inicial se faltar, recarrega systemd e habilita servico
- `before-remove`: para e desabilita servico

Esses hooks sao embutidos automaticamente pelos comandos `fpm` no `scripts/build_linux.sh`.
