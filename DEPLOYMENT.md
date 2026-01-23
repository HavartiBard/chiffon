# Chiffon MVP Deployment Guide

Production deployment to homelab infrastructure:
- **Orchestration Tier:** Unraid (192.168.20.14)
- **GPU Inference Tier:** spraycheese.lab.klsll.com (192.168.20.154) - RTX 5080
- **Reverse Proxy:** NPM on Unraid
- **Domain:** chiffon.klsll.com

## Architecture

```
User (browser)
    ↓
chiffon.klsll.com (NPM reverse proxy on Unraid)
    ├── /api/ → Orchestrator:8000
    ├── /dashboard/ → Dashboard:8001
    └── / → Frontend:3000

Orchestrator (Unraid:8000)
    ├── PostgreSQL (appdata/chiffon/postgres)
    ├── RabbitMQ (local)
    ├── LiteLLM (local)
    └── Ollama Client → http://spraycheese.lab.klsll.com:11434

Ollama Server (spraycheese.lab.klsll.com:11434)
    └── RTX 5080 GPU inference
```

## Pre-Deployment Checklist

### Unraid Setup
- [ ] Verify Docker Compose plugin installed: `docker-compose --version`
- [ ] Create directory structure:
  ```bash
  mkdir -p /mnt/user/appdata/chiffon/{postgres,config}
  mkdir -p /mnt/user/logs/chiffon
  ```
- [ ] Verify NPM container is running and healthy
- [ ] Verify DNS is configured (existing homelab-infra setup)

### Windows GPU Machine Setup
- [ ] Verify connectivity: `ping spraycheese.lab.klsll.com` (from Unraid)
- [ ] WSL2 + Docker Desktop running
- [ ] Verify GPU available in WSL2: `nvidia-smi` (in WSL2)
- [ ] Verify port 11434 is open/accessible from Unraid

### Secrets & Configuration
- [ ] Anthropic API key ready
- [ ] Create `.env` file with credentials (see template below)

## Deployment Steps

### Phase 1: Deploy Ollama to Windows GPU Machine

**On spraycheese.lab.klsll.com:**

1. Create docker-compose for Ollama:
   ```bash
   cd /path/to/workspace
   mkdir chiffon-ollama
   # Create docker-compose.yml (see below)
   ```

2. Start Ollama:
   ```bash
   docker-compose up -d
   ```

3. Verify health:
   ```bash
   curl http://localhost:11434/api/tags
   # Should return: {"models":[]}
   ```

4. Pull a model (e.g., Mistral):
   ```bash
   docker-compose exec ollama ollama pull mistral
   ```

### Phase 2: Deploy Core Services to Unraid

**On unraid.klsll.com:**

1. Clone Chiffon repo or copy docker-compose files to appdata:
   ```bash
   cp docker-compose.production.yml /mnt/user/appdata/chiffon/docker-compose.yml
   cp .env.example /mnt/user/appdata/chiffon/.env
   ```

2. Edit `.env` with your credentials:
   ```env
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-... (optional)
   LITELLM_MASTER_KEY=your-secret-key
   OLLAMA_BASE_URL=http://spraycheese.lab.klsll.com:11434
   DATABASE_URL=postgresql://agent:password@postgres:5432/agent_deploy
   ```

3. Start services:
   ```bash
   cd /mnt/user/appdata/chiffon
   docker-compose up -d
   ```

4. Monitor startup:
   ```bash
   docker-compose logs -f
   # Watch for: "Uvicorn running on http://0.0.0.0:8000"
   ```

### Phase 3: Configure NPM Reverse Proxy

Use existing homelab-infra playbook to add reverse proxy entries:

**Required Proxies:**
- `chiffon.klsll.com` → `unraid.klsll.com:8000` (Orchestrator API)
- `dashboard.chiffon.klsll.com` → `unraid.klsll.com:8001` (Dashboard)
- (Frontend at root via API)

**Or manually in NPM:**
1. Login to NPM (http://unraid.klsll.com:81)
2. Add Proxy Host for `chiffon.klsll.com`:
   - Forward Hostname/IP: `unraid.klsll.com`
   - Forward Port: `8000`
   - Access List: (your access policy)
3. Add Proxy Host for `dashboard.chiffon.klsll.com`:
   - Forward Hostname/IP: `unraid.klsll.com`
   - Forward Port: `8001`

### Phase 4: Health Check & Validation

**Verify all services healthy:**

```bash
# From Unraid
docker-compose ps
# All should show "Up" and healthy

# Verify Ollama accessible
curl http://spraycheese.lab.klsll.com:11434/api/tags

# Verify Orchestrator responding
curl http://localhost:8000/health

# Verify Dashboard responding
curl http://localhost:8001/health
```

**End-to-End Test:**

1. Open browser: `http://chiffon.klsll.com` (or `https://` if SSL configured)
2. You should see the Chiffon dashboard
3. Create a test plan via UI
4. Verify it shows available infrastructure and agents

## Docker Compose Files

### docker-compose.production.yml (Unraid)

[See below]

### docker-compose.yml (Windows GPU Machine - Ollama)

[See below]

## Troubleshooting

### Ollama Not Accessible from Unraid
- [ ] Check firewall: `ping spraycheese.lab.klsll.com`
- [ ] Check port: `curl http://spraycheese.lab.klsll.com:11434/api/tags`
- [ ] Check WSL2: `docker ps` (in WSL2 terminal)
- [ ] Check Docker Desktop: Is it running?

### Services Not Starting on Unraid
- [ ] Check logs: `docker-compose logs orchestrator`
- [ ] Check PostgreSQL: `docker-compose logs postgres`
- [ ] Check disk space: `/mnt/user` must have free space
- [ ] Check permissions: appdata directory must be writable

### NPM Reverse Proxy Not Working
- [ ] Verify NPM container healthy: `docker ps` (on Unraid)
- [ ] Verify upstream service: `curl http://unraid.klsll.com:8000/health`
- [ ] Check NPM logs: `docker logs npm`
- [ ] Verify DNS resolving: `nslookup chiffon.klsll.com`

## Post-Deployment

Once MVP is running:

1. **Test Workflows:**
   - Create a test plan (e.g., "List available services")
   - Execute and verify output
   - Check audit log in PostgreSQL

2. **Monitor:**
   - Dashboard for agent health
   - PostgreSQL for audit trail
   - Logs for any errors

3. **Patch Phase:**
   - Document any issues found
   - Create patch commits to main
   - Re-test until stable

## Next Steps

After stable deployment, we'll:
1. Test the Kuma Uptime use case (mentioned in README)
2. Deploy a sample Ansible playbook execution
3. Verify git audit trail works
4. Identify and patch any issues
5. Then proceed to Phase 2 features (desktop agents, state management, etc)

---

**Commands Reference:**

```bash
# Start/Stop
docker-compose up -d
docker-compose down
docker-compose restart

# Monitoring
docker-compose ps
docker-compose logs -f [service]

# Database
docker-compose exec postgres psql -U agent -d agent_deploy

# Check health
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8001/health  # dashboard
```
