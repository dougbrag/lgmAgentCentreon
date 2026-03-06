# LGM Monitoring Agent

Sistema de monitoramento push telemetry, leve e seguro, composto por:
- `agent/lgm_agent.py` (agent cliente, arquivo único)
- `receiver/lgm_receiver.py` (receiver server FastAPI)
- `centreon-plugin/check_lgm_metrics.py` (plugin exemplo para Centreon/Nagios)

## Arquitetura

Servidor monitorado (`lgm-agent`) envia métricas por HTTPS (`POST /ingest`) para `lgm-receiver`.

- Outbound only no host monitorado
- Autenticação por token
- Assinatura HMAC opcional (recomendado em produção)
- Integração com Centreon

## Requisitos

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1) Agent

Arquivo único: `agent/lgm_agent.py`

### Métricas coletadas
- CPU usage
- Memory usage
- Disk usage (`/`)
- Load average (1/5/15)
- Uptime
- Hostname
- Primary IP

### Endpoints usados pelo agent
- `POST /register` no primeiro start
- `POST /ingest` em intervalo configurável
- `GET /agent/version` para auto-update

### Execução

```bash
python3 agent/lgm_agent.py --config /etc/lgm-agent/config.json
```

### Utilitários embutidos

Gerar chave de token:

```bash
python3 agent/lgm_agent.py --config /etc/lgm-agent/config.json --generate-key
```

Criptografar token:

```bash
python3 agent/lgm_agent.py --config /etc/lgm-agent/config.json --encrypt-token 'SEU_TOKEN'
```

Gerar chave HMAC:

```bash
python3 agent/lgm_agent.py --config /etc/lgm-agent/config.json --generate-hmac-key
```

Criptografar segredo HMAC:

```bash
python3 agent/lgm_agent.py --config /etc/lgm-agent/config.json --encrypt-hmac-secret 'SEU_SEGREDO_HMAC'
```

## 2) Receiver

Arquivo: `receiver/lgm_receiver.py`

### Endpoints
- `POST /register`
- `POST /ingest`
- `GET /metrics?host=<hostname>`
- `GET /agent/version`

### Segurança
- Autenticação por token (`Authorization: Bearer` ou `X-Agent-Token`)
- Assinatura HMAC SHA256 por método/path/timestamp/hash-do-body
- Janela anti-replay por timestamp (`hmac_max_skew_seconds`) e nonce persistido em SQLite (`hmac_nonce_ttl_seconds`), sem servico externo
- Manutencao automatica do SQLite: limpeza periodica de nonces expirados (`nonce_cleanup_interval_seconds`) e `VACUUM` periodico (`sqlite_vacuum_interval_seconds`)
- Limite de request por tamanho (`max_request_size_bytes`)
- Validação de payload com Pydantic
- Tratamento de exceções
- Logs estruturados (JSON)

### Banco
SQLite com tabelas:
- `registrations` (registro de hosts)
- `metrics` (último payload por host)

### Execução

```bash
python3 receiver/lgm_receiver.py --config /etc/lgm-monitor/config.json
```

## 3) Plugin Centreon (exemplo)

Arquivo: `centreon-plugin/check_lgm_metrics.py`

Exemplo:

```bash
python3 centreon-plugin/check_lgm_metrics.py \
  --url https://receiver.example.com:8443 \
  --token AGENT_TOKEN \
  --host host123
```

Saída:

```text
OK - cpu 12.0% mem 30.0% disk 40.0% | cpu=12.0;80;90;0;100 mem=30.0;80;90;0;100 disk=40.0;80;90;0;100
```

## 4) Configurações

Exemplos prontos:
- `examples/agent.config.json`
- `examples/receiver.config.json`

### Agent (produção)
Copiar para:
- `/etc/lgm-agent/config.json`
- `/etc/lgm-agent/key.bin`
- `/etc/lgm-agent/token.enc`
- `/etc/lgm-agent/hmac_key.bin`
- `/etc/lgm-agent/hmac_secret.enc`

### Receiver (produção)
Copiar para:
- `/etc/lgm-monitor/config.json`
- `/etc/lgm-monitor/key.bin`
- `/etc/lgm-monitor/centreon_token.enc`
- `/etc/lgm-monitor/hmac_key.bin`
- `/etc/lgm-monitor/hmac_secret.enc`

## 5) Exemplo de criptografia de token/segredo

Script utilitário:
- `scripts/encrypt_token.py`

Uso (agent token):

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-agent/key.bin \
  --token-file /etc/lgm-agent/token.enc \
  --token 'AGENT_TOKEN_AQUI'
```

Uso (segredo HMAC no agent):

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-agent/hmac_key.bin \
  --token-file /etc/lgm-agent/hmac_secret.enc \
  --token 'SEGREDO_HMAC_COMPARTILHADO'
```

Uso (segredo HMAC no receiver):

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-monitor/hmac_key.bin \
  --token-file /etc/lgm-monitor/hmac_secret.enc \
  --token 'SEGREDO_HMAC_COMPARTILHADO'
```

Uso (receiver/Centreon API token):

```bash
python3 scripts/encrypt_token.py \
  --key-file /etc/lgm-monitor/key.bin \
  --token-file /etc/lgm-monitor/centreon_token.enc \
  --token 'CENTREON_API_TOKEN_AQUI'
```

## 6) Compilação standalone

### PyInstaller

Agent:

```bash
pyinstaller --onefile --name lgm-agent agent/lgm_agent.py
```

Receiver:

```bash
pyinstaller --onefile --name lgm-receiver receiver/lgm_receiver.py
```

Plugin (opcional):

```bash
pyinstaller --onefile --name check_lgm_metrics centreon-plugin/check_lgm_metrics.py
```

### Nuitka

Agent:

```bash
python3 -m nuitka --onefile --standalone --output-filename=lgm-agent agent/lgm_agent.py
```

Receiver:

```bash
python3 -m nuitka --onefile --standalone --output-filename=lgm-receiver receiver/lgm_receiver.py
```

Plugin:

```bash
python3 -m nuitka --onefile --standalone --output-filename=check_lgm_metrics centreon-plugin/check_lgm_metrics.py
```

## 7) Instalação Linux

### Diretórios

```bash
sudo mkdir -p /etc/lgm-agent /etc/lgm-monitor /var/lib/lgm-monitor /var/log/lgm-agent /var/log/lgm-monitor
```

### Binários

```bash
sudo install -m 0755 dist/lgm-agent /usr/local/bin/lgm-agent
sudo install -m 0755 dist/lgm-receiver /usr/local/bin/lgm-receiver
sudo install -m 0755 centreon-plugin/check_lgm_metrics.py /usr/lib/centreon/plugins/check_lgm_metrics
```

### Services systemd

Arquivos prontos em:
- `deploy/systemd/lgm-agent.service`
- `deploy/systemd/lgm-receiver.service`

Instalação:

```bash
sudo cp deploy/systemd/lgm-agent.service /etc/systemd/system/
sudo cp deploy/systemd/lgm-receiver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lgm-agent
sudo systemctl enable --now lgm-receiver
```

## Observações de evolução

- Estrutura de plugin interna do agent já preparada para `AsteriskPlugin` e `MySQLPlugin`.
- Auto-update valida SHA256 antes de substituir binário.
- HMAC já implementado e pode ser desativado por configuração (`hmac_enabled=false`) para rollout gradual.



## 8) Build Linux DEB/RPM

Script pronto:
- `scripts/build_linux.sh`

### Requisitos no Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller
# instalar fpm (exemplo Debian/Ubuntu)
sudo apt-get install -y ruby ruby-dev build-essential
sudo gem install --no-document fpm
```

### Gerar pacotes localmente

```bash
chmod +x scripts/build_linux.sh
# gera .deb e .rpm
scripts/build_linux.sh 1.0.0 artifacts

# apenas .deb
scripts/build_linux.sh 1.0.0 artifacts deb

# apenas .rpm
scripts/build_linux.sh 1.0.0 artifacts rpm
```

## 9) CI para pacotes Linux

Workflow:
- `.github/workflows/build-linux-packages.yml`

Execucao:
- manual via `workflow_dispatch`
- automatica ao publicar tag `v*` (ex.: `v1.0.0`)

Artefatos gerados no GitHub Actions:
- `deb-packages` (`*.deb`)
- `rpm-packages` (`*.rpm`)
- `deb-packages` tambem inclui `SHA256SUMS-deb.txt`
- `rpm-packages` tambem inclui `SHA256SUMS-rpm.txt`

Publicacao automatica em Release (quando tag `v*`):
- anexa todos os `.deb` e `.rpm`
- anexa checksums individuais e consolidado (`SHA256SUMS.txt`)
- gera release notes automaticamente

HOWTO completo: docs/HOWTO_IMPLEMENTACAO_E_USO.md

## 10) Automacao de implantacao

Scripts de bootstrap (instalacao manual por binario):

```bash
# agent
sudo bash scripts/bootstrap_agent.sh dist/lgm-agent

# receiver
sudo bash scripts/bootstrap_receiver.sh dist/lgm-receiver
```

Para iniciar servico automaticamente no bootstrap:

```bash
sudo bash scripts/bootstrap_agent.sh dist/lgm-agent start
sudo bash scripts/bootstrap_receiver.sh dist/lgm-receiver start
```

Automacao via DEB/RPM (hooks incluidos no pacote):
- `post-install`: cria diretorios, copia `config.json.example` para `config.json` se ausente, `daemon-reload`, `enable` do service
- `before-remove`: `stop` + `disable` do service

## 11) RPM especifico para CentOS 7 (glibc 2.17)

O pipeline agora gera um RPM dedicado para CentOS 7 usando base compativel com `glibc 2.17`.

No Release, prefira o pacote com iteracao `el7`, por exemplo:
- `lgm-agent-<versao>-1.el7.x86_64.rpm`
- `lgm-receiver-<versao>-1.el7.x86_64.rpm`

Em servidores CentOS 7, instale sempre os `*.el7.x86_64.rpm`.
