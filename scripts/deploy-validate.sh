#!/bin/bash

# Chiffon Deployment Validation Script
# Post-deployment health checks and service verification
#
# Usage: bash scripts/deploy-validate.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
UNRAID_HOST="unraid.klsll.com"
UNRAID_IP="192.168.20.14"
WINDOWS_HOST="spraycheese.lab.klsll.com"

# Counters
PASSED=0
FAILED=0

# ============================================================================
# Helper Functions
# ============================================================================

test_pass() {
    echo -e "${GREEN}[✓]${NC} $*"
    ((PASSED++))
}

test_fail() {
    echo -e "${RED}[✗]${NC} $*"
    ((FAILED++))
}

test_skip() {
    echo -e "${YELLOW}[~]${NC} $*"
}

# ============================================================================
# Validation Tests
# ============================================================================

test_network() {
    echo ""
    echo -e "${BLUE}=== Network Connectivity ===${NC}"

    if ping -c 1 "$UNRAID_IP" &> /dev/null; then
        test_pass "Ping Unraid ($UNRAID_IP)"
    else
        test_fail "Ping Unraid ($UNRAID_IP)"
    fi

    if ping -c 1 "$WINDOWS_HOST" &> /dev/null; then
        test_pass "Ping Windows GPU machine"
    else
        test_fail "Ping Windows GPU machine"
    fi
}

test_ollama() {
    echo ""
    echo -e "${BLUE}=== Ollama Service ===${NC}"

    # Health check
    if curl -s "http://${WINDOWS_HOST}:11434/api/tags" &> /dev/null; then
        test_pass "Ollama API health check"
    else
        test_fail "Ollama API health check"
        return 1
    fi

    # List models
    local models=$(curl -s "http://${WINDOWS_HOST}:11434/api/tags" | grep -o '"name":"[^"]*"' | wc -l)
    if [ "$models" -gt 0 ]; then
        test_pass "Ollama has $models model(s) loaded"
    else
        test_skip "Ollama has no models loaded (pull models with: docker-compose exec ollama ollama pull mistral)"
    fi
}

test_orchestrator() {
    echo ""
    echo -e "${BLUE}=== Orchestrator Service ===${NC}"

    # Health check
    if curl -s "http://${UNRAID_IP}:8000/health" &> /dev/null; then
        test_pass "Orchestrator API health check"
    else
        test_fail "Orchestrator API health check"
        return 1
    fi

    # Check if accessible via hostname
    if curl -s "http://${UNRAID_HOST}:8000/health" &> /dev/null; then
        test_pass "Orchestrator accessible via hostname"
    else
        test_fail "Orchestrator accessible via hostname (DNS issue?)"
    fi
}

test_database() {
    echo ""
    echo -e "${BLUE}=== PostgreSQL Database ===${NC}"

    # Check if postgres container is running
    if curl -s "http://${UNRAID_IP}:8000/health" &> /dev/null; then
        test_pass "PostgreSQL container is running (inferred from Orchestrator health)"
    else
        test_skip "PostgreSQL health check (requires SSH access to Unraid)"
    fi
}

test_dashboard() {
    echo ""
    echo -e "${BLUE}=== Dashboard Service ===${NC}"

    if curl -s "http://${UNRAID_IP}:8001/health" &> /dev/null; then
        test_pass "Dashboard API health check"
    else
        test_fail "Dashboard API health check"
        return 1
    fi

    if curl -s "http://${UNRAID_HOST}:8001/health" &> /dev/null; then
        test_pass "Dashboard accessible via hostname"
    else
        test_skip "Dashboard accessible via hostname (DNS issue?)"
    fi
}

test_frontend() {
    echo ""
    echo -e "${BLUE}=== Frontend Service ===${NC}"

    if curl -s "http://${UNRAID_IP}:3000" &> /dev/null; then
        test_pass "Frontend is responding"
    else
        test_fail "Frontend is responding"
        return 1
    fi

    if curl -s "http://${UNRAID_HOST}:3000" &> /dev/null; then
        test_pass "Frontend accessible via hostname"
    else
        test_skip "Frontend accessible via hostname (DNS issue?)"
    fi
}

test_connectivity() {
    echo ""
    echo -e "${BLUE}=== Cross-Service Connectivity ===${NC}"

    # Test Orchestrator → Ollama connectivity
    # (This would require shell access to Orchestrator container)
    test_skip "Orchestrator ↔ Ollama connectivity (requires container shell access)"

    # Test Orchestrator → Database connectivity
    test_skip "Orchestrator ↔ PostgreSQL connectivity (requires container shell access)"
}

test_npm_proxy() {
    echo ""
    echo -e "${BLUE}=== NPM Reverse Proxy ===${NC}"

    # Try to access via NPM-proxied domain
    if curl -s "http://chiffon.klsll.com/health" &> /dev/null; then
        test_pass "NPM proxy for chiffon.klsll.com is working"
    else
        test_skip "NPM proxy for chiffon.klsll.com not configured or not accessible"
    fi

    if curl -s "http://dashboard.chiffon.klsll.com/health" &> /dev/null; then
        test_pass "NPM proxy for dashboard.chiffon.klsll.com is working"
    else
        test_skip "NPM proxy for dashboard.chiffon.klsll.com not configured"
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║ Chiffon MVP Deployment Validation     ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"

    test_network
    test_ollama
    test_orchestrator
    test_database
    test_dashboard
    test_frontend
    test_connectivity
    test_npm_proxy

    # Summary
    echo ""
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${GREEN}Passed: $PASSED${NC}"
    echo -e "${RED}Failed: $FAILED${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"

    if [ $FAILED -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✓ All validation tests passed!${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Access dashboard: http://${UNRAID_HOST}:8001"
        echo "  2. Access frontend: http://${UNRAID_HOST}:3000"
        echo "  3. Create a test plan in the dashboard"
        echo "  4. Monitor logs: docker-compose logs -f orchestrator"
        echo ""
        return 0
    else
        echo ""
        echo -e "${RED}✗ Some tests failed. Check configuration and try again.${NC}"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check network connectivity: ping $UNRAID_IP && ping $WINDOWS_HOST"
        echo "  2. Check service logs on Unraid: docker-compose logs"
        echo "  3. Verify .env configuration: /mnt/user/appdata/chiffon/.env"
        echo "  4. Restart services: docker-compose down && docker-compose up -d"
        echo ""
        return 1
    fi
}

main "$@"
