#!/bin/bash

# Chiffon Production MVP Deployment Script
# Validates environment, deploys to Unraid, and tests connectivity
#
# Usage: bash scripts/deploy-production.sh [--windows-ollama] [--unraid] [--full]
#
# Flags:
#   --windows-ollama  Deploy Ollama to Windows GPU machine only
#   --unraid          Deploy core services to Unraid only
#   --full            Deploy everything (Ollama + Unraid services)

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
UNRAID_HOST="unraid.lab.klsll.com"
UNRAID_IP="192.168.20.14"
WINDOWS_HOST="spraycheese.lab.klsll.com"
WINDOWS_IP="192.168.20.154"
APPDATA_PATH="/mnt/user/appdata/chiffon"
SSH_KEY="$HOME/.ssh/id_ed25519_homelab"

# Script state
DEPLOY_LLAMACPP=${DEPLOY_LLAMACPP:-false}
DEPLOY_UNRAID=${DEPLOY_UNRAID:-false}
DEPLOY_FULL=${DEPLOY_FULL:-false}

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $*"
}

log_error() {
    echo -e "${RED}[✗]${NC} $*"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        log_success "Found: $1"
        return 0
    else
        log_error "Missing: $1"
        return 1
    fi
}

# ============================================================================
# Pre-Deployment Checks
# ============================================================================

check_local_environment() {
    log_info "Checking local environment..."

    local failed=0

    # Check commands
    check_command "docker" || ((failed++))
    check_command "docker-compose" || ((failed++))
    check_command "curl" || ((failed++))
    check_command "ssh" || ((failed++))

    if [ $failed -gt 0 ]; then
        log_error "Missing $failed required commands"
        return 1
    fi

    log_success "Local environment OK"
    return 0
}

check_network_connectivity() {
    log_info "Checking network connectivity..."

    # Check Unraid
    if ping -c 1 "$UNRAID_IP" &> /dev/null; then
        log_success "Unraid reachable: $UNRAID_HOST ($UNRAID_IP)"
    else
        log_error "Cannot reach Unraid: $UNRAID_HOST ($UNRAID_IP)"
        return 1
    fi

    # Check Windows GPU machine
    if ping -c 1 "$WINDOWS_IP" &> /dev/null; then
        log_success "Windows GPU machine reachable: $WINDOWS_HOST ($WINDOWS_IP)"
    else
        log_error "Cannot reach Windows GPU machine: $WINDOWS_HOST ($WINDOWS_IP)"
        return 1
    fi

    log_success "Network connectivity OK"
    return 0
}

check_env_file() {
    log_info "Checking environment configuration..."

    if [ ! -f ".env.production" ]; then
        log_warning "Missing .env.production file"
        log_info "Copy and edit: cp .env.production.example .env.production"
        return 1
    fi

    # Check for required API keys
    if ! grep -q "OPENAI_API_KEY=sk-" .env.production; then
        log_error "OPENAI_API_KEY not configured in .env.production"
        return 1
    fi

    log_success "Environment configuration OK"
    return 0
}

# ============================================================================
# Deployment Functions
# ============================================================================

deploy_llamacpp_windows() {
    log_info "Deploying llama.cpp to Windows GPU machine..."

    # Copy docker-compose to Windows via SSH (assumes SSH set up)
    log_info "Copying docker-compose.llamacpp.yml to Windows..."

    if scp -i "${SSH_KEY}" docker-compose.llamacpp.yml "james@${WINDOWS_HOST}:~/chiffon/docker-compose.yml" 2>/dev/null; then
        log_success "docker-compose copied"
    else
        log_warning "Could not SCP file (SSH may not be configured)"
        log_info "Manual step: Copy docker-compose.llamacpp.yml to Windows and run:"
        log_info "  1. Place quantized model in ~/chiffon/models/"
        log_info "  2. cd ~/chiffon && docker-compose up -d"
        return 1
    fi

    # Start services via SSH
    log_info "Starting llama.cpp service..."
    if ssh -i "${SSH_KEY}" "james@${WINDOWS_HOST}" "cd ~/chiffon && docker-compose up -d" 2>/dev/null; then
        log_success "llama.cpp service started"
    else
        log_warning "Could not start via SSH"
        return 1
    fi

    # Wait for llama.cpp to be ready
    log_info "Waiting for llama.cpp to be ready..."
    for i in {1..60}; do
        if curl -s "http://${WINDOWS_HOST}:8000/health" &> /dev/null; then
            log_success "llama.cpp is ready"
            return 0
        fi
        echo -n "."
        sleep 2
    done

    log_error "llama.cpp failed to start within 120 seconds"
    return 1
}

deploy_unraid_services() {
    log_info "Deploying core services to Unraid..."

    # Check if we can access Unraid
    if ! ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "ls ${APPDATA_PATH}" &> /dev/null; then
        log_error "Cannot access Unraid via SSH (root@${UNRAID_HOST})"
        log_warning "Manual deployment required:"
        log_info "  1. SCP files to Unraid:"
        log_info "     scp -i ${SSH_KEY} docker-compose.production.yml root@${UNRAID_HOST}:${APPDATA_PATH}/"
        log_info "     scp -i ${SSH_KEY} .env.production root@${UNRAID_HOST}:${APPDATA_PATH}/.env"
        log_info "  2. SSH and start:"
        log_info "     ssh -i ${SSH_KEY} root@${UNRAID_HOST}"
        log_info "     cd ${APPDATA_PATH}"
        log_info "     docker-compose up -d"
        return 1
    fi

    # Create directories on Unraid
    log_info "Creating directories on Unraid..."
    ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "mkdir -p ${APPDATA_PATH}/{postgres,config}" || true

    # Copy docker-compose and .env
    log_info "Copying files to Unraid..."
    scp -i "${SSH_KEY}" docker-compose.production.yml "root@${UNRAID_HOST}:${APPDATA_PATH}/docker-compose.yml"
    scp -i "${SSH_KEY}" .env.production "root@${UNRAID_HOST}:${APPDATA_PATH}/.env"
    scp -i "${SSH_KEY}" config/litellm-config.json "root@${UNRAID_HOST}:${APPDATA_PATH}/config/"
    log_success "Files copied"

    # Start services via SSH
    log_info "Starting services on Unraid..."
    ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "cd ${APPDATA_PATH} && docker-compose up -d" || {
        log_error "Failed to start services"
        return 1
    }

    log_success "Core services started"

    # Wait for services to be healthy
    log_info "Waiting for services to be healthy..."
    local max_attempts=60
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "docker-compose -f ${APPDATA_PATH}/docker-compose.yml ps" | grep -q "Up"; then
            log_success "Services are up"
            return 0
        fi
        echo -n "."
        sleep 2
        ((attempt++))
    done

    log_error "Services failed to start within 120 seconds"
    return 1
}

# ============================================================================
# Post-Deployment Validation
# ============================================================================

validate_deployment() {
    log_info "Validating deployment..."

    local failed=0

    # Check llama.cpp
    log_info "Checking llama.cpp..."
    if curl -s "http://${WINDOWS_HOST}:8000/health" &> /dev/null; then
        log_success "llama.cpp API responding"
    else
        log_error "llama.cpp API not responding"
        ((failed++))
    fi

    # Check Unraid services
    log_info "Checking Unraid services..."

    # Orchestrator health
    if curl -s "http://${UNRAID_HOST}:8000/health" &> /dev/null; then
        log_success "Orchestrator API responding"
    else
        log_error "Orchestrator API not responding"
        ((failed++))
    fi

    # Dashboard health
    if curl -s "http://${UNRAID_HOST}:8001/health" &> /dev/null; then
        log_success "Dashboard responding"
    else
        log_error "Dashboard not responding"
        ((failed++))
    fi

    # Frontend health
    if curl -s "http://${UNRAID_HOST}:3000" &> /dev/null; then
        log_success "Frontend responding"
    else
        log_error "Frontend not responding"
        ((failed++))
    fi

    if [ $failed -eq 0 ]; then
        log_success "All services validated"
        return 0
    else
        log_error "$failed services failed validation"
        return 1
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    log_info "Chiffon Production Deployment"
    log_info "========================================"

    # Parse arguments
    if [ $# -gt 0 ]; then
        case "$1" in
            --windows-llamacpp) DEPLOY_LLAMACPP=true ;;
            --unraid) DEPLOY_UNRAID=true ;;
            --full) DEPLOY_LLAMACPP=true; DEPLOY_UNRAID=true ;;
            --help)
                echo "Usage: $0 [--windows-llamacpp] [--unraid] [--full]"
                echo ""
                echo "Flags:"
                echo "  --windows-llamacpp  Deploy llama.cpp to Windows GPU machine (RTX 5080)"
                echo "  --unraid            Deploy core services to Unraid"
                echo "  --full              Deploy everything"
                exit 0
                ;;
            *)
                log_error "Unknown flag: $1"
                exit 1
                ;;
        esac
    else
        # Default: full deployment
        DEPLOY_LLAMACPP=true
        DEPLOY_UNRAID=true
    fi

    # Pre-deployment checks
    check_local_environment || exit 1
    check_network_connectivity || exit 1
    check_env_file || exit 1

    # Deployment
    if [ "$DEPLOY_LLAMACPP" = true ]; then
        deploy_llamacpp_windows || log_warning "llama.cpp deployment failed (may need manual deployment)"
    fi

    if [ "$DEPLOY_UNRAID" = true ]; then
        deploy_unraid_services || exit 1
    fi

    # Validation
    validate_deployment || log_warning "Some services may not be ready yet"

    log_info ""
    log_success "Deployment complete!"
    log_info ""
    log_info "Next steps:"
    log_info "1. Verify deployment: bash scripts/deploy-validate.sh"
    log_info "2. Access dashboard: http://chiffon.klsll.com or http://${UNRAID_HOST}:8001"
    log_info "3. Access frontend: http://${UNRAID_HOST}:3000"
    log_info ""
}

main "$@"
