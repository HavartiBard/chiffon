# Gitea Runner Requirements

This document outlines the requirements for setting up Gitea Runner instances to execute CI/CD workflows for the chiffon project.

## Overview

Gitea Runners are self-hosted agents that execute jobs from Gitea Actions workflows. They must be set up and registered with the Gitea instance to execute the chiffon CI/CD pipeline.

## System Requirements

### Minimum Specifications
- **CPU**: 2+ cores
- **Memory**: 4GB RAM minimum (8GB+ recommended for Docker image builds)
- **Storage**: 20GB+ available (for Docker layer caching and image builds)
- **Network**: Reliable connection to `gitea.klsll.com`

### Supported Platforms
- Linux (Ubuntu 20.04+ recommended)
- Docker installed and running
- Docker daemon accessible to the runner process

## Software Dependencies

### Required
- **Gitea Runner**: Latest stable version (act_runner or gitea-runner)
- **Docker**: For building and pushing container images
- **Docker Compose**: For running containerized workloads

### Optional but Recommended
- **Git**: For repository operations
- **curl/wget**: For health checks and diagnostics

## Gitea Integration Requirements

### Gitea Instance Connection
- **URL**: `https://gitea.klsll.com`
- **Authentication**: Gitea Runner Token (generated from Gitea)
- **Permissions**: Token must have runner registration and job execution scopes

### Token Generation (Gitea Admin)
1. Log into Gitea as admin
2. Navigate to Admin Panel → Runners
3. Create a new runner token with appropriate scopes
4. Token required during runner initialization

## Runner Configuration

### Labels
The runner must be registered with the following labels to match workflow requirements:

```
- ubuntu-latest
- linux
- docker
```

Additional optional labels:
```
- gpu (if GPU access available)
- high-memory (if 16GB+ RAM)
```

### Workspace Configuration
- **Workspace Directory**: `/opt/gitea-runner/workspace` or equivalent
- **Artifacts Directory**: Must support temporary file storage during builds
- **Log Directory**: For runner and job logs

## Docker & Registry Requirements

### Docker-in-Docker (DinD)
- Runner must have Docker access (either via socket mount or DinD)
- Ability to build, tag, and push Docker images
- Access to Docker daemon with sufficient permissions

### Registry Access
- **Registry URL**: `registry.klsll.com`
- **Authentication**:
  - Username: Gitea username (e.g., `HavartiBard`)
  - Password: Gitea personal access token or password
- **Required Scopes**: Read/write access to registry
- Credentials stored securely in runner environment or Gitea secrets

## Networking Requirements

### Outbound Connectivity
- `gitea.klsll.com` (HTTPS/SSH) - Gitea instance
- `registry.klsll.com` (HTTPS) - Container registry
- GitHub APIs (if pulling actions from GitHub)
- Docker Hub or other public registries (if pulling base images)

### Inbound (Optional)
- Health check endpoints from monitoring
- SSH if remote management desired

## Job Execution Requirements

### Environment Variables (to configure)
```
GITEA_RUNNER_NAME=chiffon-runner-1      # Unique runner identifier
GITEA_RUNNER_LABELS=ubuntu-latest,linux,docker
DOCKER_HOST=unix:///var/run/docker.sock # Docker socket or DinD endpoint
REGISTRY_URL=registry.klsll.com
```

### Resource Limits per Job
- **CPU**: No hard limit, but 2 cores minimum recommended per concurrent job
- **Memory**: 2-4GB per job
- **Disk**: 5-10GB per job (for image layer cache)
- **Concurrent Jobs**: Start with 1-2, scale based on available resources

## Deployment Considerations

### Container vs Host Installation
- **Recommended**: Run Gitea Runner as a container (Docker) for isolation
- **Alternative**: Host installation if preferred

### Data Persistence
- Runner state and configuration should persist across restarts
- Use Docker volumes or host bind mounts for `/opt/gitea-runner` directory

### High Availability (Optional)
- Multiple runner instances can be registered with different names
- All will pull from the same job queue
- Recommended: 2-3 runners for redundancy

## Security Requirements

### Credentials Management
- Runner token stored securely (environment variable or secret manager)
- Docker registry credentials in runner environment or via credential helpers
- SSH keys (if needed) mounted securely with restricted permissions (0600)

### Network Isolation
- Runner should run in trusted network environment
- If exposed to untrusted networks, use firewall rules to restrict Gitea access
- HTTPS required for all communication

## Health & Monitoring

### Health Checks
- Runner continuously connects to Gitea at `gitea.klsll.com`
- Logs available for debugging job execution
- Failed jobs should be visible in Gitea web UI

### Logging
- Runner logs to stdout/stderr (captured by Docker/systemd)
- Job logs stored and accessible via Gitea web UI
- Retention: Keep last 30 days of logs minimum

## Workflow-Specific Requirements

### For chiffon CI Pipeline
- **lint job**: Python 3.11 with Poetry support
- **test job**: Python 3.11 with pytest and Poetry
- **build job**: Docker buildx for multi-platform builds
- **publish job**: Docker login and push to `registry.klsll.com`

### Required CLI Tools in Runner Image
- `git`
- `curl`/`wget`
- `docker`
- `python3.11` (or via Python action)
- `poetry` (or installed via CI steps)

## Testing the Setup

Once runners are deployed, verify:

1. Runner appears online in Gitea Admin Panel → Runners
2. Runner has correct labels assigned
3. Test job triggers: Push to `phase/01-foundation` branch
4. Logs show successful execution
5. Docker images successfully pushed to `registry.klsll.com`

## Scaling & Future Considerations

- Start with 1 runner, add more based on job queue depth
- Monitor CPU/memory usage during builds
- Consider separate runners for fast (lint/test) vs slow (build/publish) jobs
- GPU runners optional if image build optimization needed

---

**Next Steps**: Create Ansible playbook in `homelab_infra` repo to deploy and register Gitea Runner(s) with these specifications.
