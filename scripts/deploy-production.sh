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

# Deployment tuning
HEALTH_RETRY_INTERVAL=2
LLAMACPP_HEALTH_RETRIES=90
UNRAID_HEALTH_RETRIES=90

# Script state
DEPLOY_LLAMACPP=${DEPLOY_LLAMACPP:-false}
DEPLOY_UNRAID=${DEPLOY_UNRAID:-false}

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

set_deploy_targets() {
    local target_value normalized
    target_value="$1"
    normalized="$(echo "${target_value}" | tr '[:upper:]' '[:lower:]')"

    case "${normalized}" in
        windows|llamacpp)
            DEPLOY_LLAMACPP=true
            DEPLOY_UNRAID=false
            ;;
        unraid)
            DEPLOY_UNRAID=true
            DEPLOY_LLAMACPP=false
            ;;
        full|all)
            DEPLOY_LLAMACPP=true
            DEPLOY_UNRAID=true
            ;;
        *)
            log_error "Unknown target: ${target_value}"
            return 1
            ;;
    esac

    return 0
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

    # Create directories on Windows first
    log_info "Creating directories on Windows GPU machine..."
    if ! ssh -i "${SSH_KEY}" "james@${WINDOWS_HOST}" "mkdir -p ~/chiffon/models ~/chiffon/cache"; then
        log_error "Failed to create directories on Windows"
        return 1
    fi
    log_success "Directories created on Windows"

    # Copy docker-compose and Dockerfile to Windows via SSH
    log_info "Copying deployment files to Windows..."
    log_info "DEBUG: Using SSH key: ${SSH_KEY}"
    log_info "DEBUG: Target: james@${WINDOWS_HOST}"

    if ! scp -i "${SSH_KEY}" docker-compose.llamacpp.yml "james@${WINDOWS_HOST}:~/chiffon/docker-compose.yml"; then
        log_warning "Could not SCP docker-compose file"
        log_info "Manual step: Copy files to ~/chiffon/ and run docker-compose up -d"
        return 1
    fi
    log_success "docker-compose.yml copied"

    if ! scp -i "${SSH_KEY}" Dockerfile.llamacpp "james@${WINDOWS_HOST}:~/chiffon/"; then
        log_warning "Could not SCP Dockerfile"
        log_info "Note: Dockerfile.llamacpp is required for building the image"
        return 1
    fi
    log_success "Dockerfile.llamacpp copied"

    # Start services via SSH
    log_info "Starting llama.cpp service..."
    if ssh -i "${SSH_KEY}" "james@${WINDOWS_HOST}" "cd ~/chiffon && docker-compose up -d"; then
        log_success "llama.cpp service started"
    else
        log_warning "Could not start via SSH"
        return 1
    fi

    # Wait for llama.cpp to be ready
    log_info "Waiting for llama.cpp to be ready..."
    for ((i = 1; i <= LLAMACPP_HEALTH_RETRIES; i++)); do
        if curl -s "http://${WINDOWS_HOST}:8000/health" &> /dev/null; then
            log_success "llama.cpp is ready"
            return 0
        fi
        echo -n "."
        sleep "${HEALTH_RETRY_INTERVAL}"
    done

    log_error "llama.cpp failed to start within $((LLAMACPP_HEALTH_RETRIES * HEALTH_RETRY_INTERVAL)) seconds"
    return 1
}

deploy_unraid_services() {
    log_info "Deploying core services to Unraid..."
    log_info "DEBUG: Using SSH key: ${SSH_KEY}"
    log_info "DEBUG: Target: root@${UNRAID_HOST}"

    # Create appdata directory on Unraid
    log_info "Creating appdata directory on Unraid..."
    if ! ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "mkdir -p ${APPDATA_PATH}"; then
        log_error "Failed to create appdata directory on Unraid"
        return 1
    fi
    log_success "Appdata directory created"

    # Clone the Chiffon repository to Unraid (or update if exists)
    log_info "Cloning Chiffon repository to Unraid..."
    if ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "test -d ${APPDATA_PATH}/chiffon"; then
        log_info "Repository already exists, updating..."
        if ! ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "cd ${APPDATA_PATH}/chiffon && git pull origin phase/01-foundation"; then
            log_warning "Could not update repository, continuing with existing version"
        fi
    else
        if ! ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "cd ${APPDATA_PATH} && git clone -b phase/01-foundation https://github.com/HavartiBard/chiffon.git"; then
            log_error "Failed to clone Chiffon repository to Unraid"
            return 1
        fi
        log_success "Chiffon repository cloned"
    fi

    # Create directories on Unraid for persistent data
    log_info "Creating data directories on Unraid..."
    if ! ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "mkdir -p ${APPDATA_PATH}/postgres ${APPDATA_PATH}/logs"; then
        log_error "Failed to create data directories"
        return 1
    fi
    log_success "Data directories created"

    # Copy .env file
    log_info "Copying .env.production to Unraid..."
    if ! scp -i "${SSH_KEY}" .env.production "root@${UNRAID_HOST}:${APPDATA_PATH}/chiffon/.env"; then
        log_error "Failed to copy .env.production"
        return 1
    fi
    log_success ".env file copied"

    # Start services via SSH
    log_info "Starting services on Unraid..."
    ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "cd ${APPDATA_PATH}/chiffon && docker-compose -f docker-compose.production.yml up -d" || {
        log_error "Failed to start services"
        return 1
    }

    log_success "Core services started"

    # Wait for services to be healthy
    log_info "Waiting for services to be healthy..."
    local max_attempts=${UNRAID_HEALTH_RETRIES}
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if ssh -i "${SSH_KEY}" "root@${UNRAID_HOST}" "cd ${APPDATA_PATH}/chiffon && docker-compose -f docker-compose.production.yml ps" | grep -q "Up"; then
            log_success "Services are up"
            return 0
        fi
        echo -n "."
        sleep "${HEALTH_RETRY_INTERVAL}"
        ((attempt++))
    done

    log_error "Services failed to start within $((max_attempts * HEALTH_RETRY_INTERVAL)) seconds"
    return 1
}

# ============================================================================
# Post-Deployment Validation
# ============================================================================

validate_deployment() {
    log_info "Validating deployment..."

    local failed=0

    if [ "$DEPLOY_LLAMACPP" = true ]; then
        log_info "Checking llama.cpp..."
        if curl -s "http://${WINDOWS_HOST}:8000/health" &> /dev/null; then
            log_success "llama.cpp API responding"
        else
            log_error "llama.cpp API not responding"
            ((failed++))
        fi
    else
        log_info "Skipping llama.cpp validation (not targeted)"
    fi

    if [ "$DEPLOY_UNRAID" = true ]; then
        log_info "Checking Unraid services..."

        if curl -s "http://${UNRAID_HOST}:8000/health" &> /dev/null; then
            log_success "Orchestrator API responding"
        else
            log_error "Orchestrator API not responding"
            ((failed++))
        fi

        if curl -s "http://${UNRAID_HOST}:8001/health" &> /dev/null; then
            log_success "Dashboard responding"
        else
            log_error "Dashboard not responding"
            ((failed++))
        fi

        if curl -s "http://${UNRAID_HOST}:3000" &> /dev/null; then
            log_success "Frontend responding"
        else
            log_error "Frontend not responding"
            ((failed++))
        fi
    else
        log_info "Skipping Unraid validation (not targeted)"
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

    local target_specified=false

    while [ $# -gt 0 ]; do
        case "$1" in
            --windows-llamacpp)
                DEPLOY_LLAMACPP=true
                target_specified=true
                shift
                ;;
            --unraid)
                DEPLOY_UNRAID=true
                target_specified=true
                shift
                ;;
            --full)
                DEPLOY_LLAMACPP=true
                DEPLOY_UNRAID=true
                target_specified=true
                shift
                ;;
            --target=*)
                if ! set_deploy_targets "${1#*=}"; then
                    exit 1
                fi
                target_specified=true
                shift
                ;;
            --target)
                shift
                if [ $# -eq 0 ]; then
                    log_error "Missing argument for --target"
                    exit 1
                fi
                if ! set_deploy_targets "$1"; then
                    exit 1
                fi
                target_specified=true
                shift
                ;;
            --help)
                echo "Usage: $0 [--windows-llamacpp] [--unraid] [--full] [--target <windows|unraid|full>]"
                echo ""
                echo "Flags:"
                echo "  --windows-llamacpp      Deploy llama.cpp to Windows GPU machine (RTX 5080)"
                echo "  --unraid                Deploy core services to Unraid"
                echo "  --full                  Deploy everything"
                echo "  --target <value>        Shortcut to focus on a single deploy target (windows, unraid, full)"
                exit 0
                ;;
            *)
                log_error "Unknown flag: $1"
                exit 1
                ;;
        esac
    done

    if [ "$target_specified" = false ]; then
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
