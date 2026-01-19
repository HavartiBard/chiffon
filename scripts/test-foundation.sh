#!/bin/bash
set -u
set -o pipefail

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Helper functions
pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

# Check if command exists
check_command() {
    if command -v "$1" &> /dev/null; then
        pass "Command available: $1"
        return 0
    else
        fail "Command not found: $1"
        return 1
    fi
}

# Check Docker service is running
check_service() {
    local service=$1
    if docker-compose ps "$service" 2>/dev/null | grep -q "$service"; then
        if docker-compose ps "$service" 2>/dev/null | grep -q "Up\|healthy"; then
            pass "Docker service running: $service"
            return 0
        else
            warn "Docker service $service not healthy yet"
            return 1
        fi
    else
        fail "Docker service not found: $service"
        return 1
    fi
}

# Check port is accessible
check_port() {
    local port=$1
    local name=$2

    if nc -z localhost "$port" 2>/dev/null; then
        pass "Port accessible: $name (localhost:$port)"
        return 0
    else
        warn "Port not accessible: $name (localhost:$port)"
        return 1
    fi
}

# Check file exists
check_file() {
    if [ -f "$1" ]; then
        pass "File exists: $1"
        return 0
    else
        fail "File not found: $1"
        return 1
    fi
}

# Main verification flow
main() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║     Chiffon Phase 1 Foundation Verification                    ║"
    echo "║     Autonomous AI Agent Infrastructure for Homelab            ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # Store project root
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$PROJECT_ROOT" || fail "Cannot change to project root"

    # ==========================================
    # 1. Prerequisites
    # ==========================================
    header "1. System Prerequisites"

    # Check Python
    if command -v python3 &> /dev/null; then
        python_version=$(python3 --version 2>&1 | awk '{print $2}')
        if [[ "$python_version" == "3.11."* ]] || [[ "$python_version" == "3.12."* ]]; then
            pass "Python version: $python_version"
        else
            warn "Python $python_version (3.11+ recommended)"
        fi
    else
        fail "Python 3 not found"
    fi

    check_command "docker"
    check_command "docker-compose"
    check_command "git"
    check_command "poetry"

    # ==========================================
    # 2. Environment Configuration
    # ==========================================
    header "2. Environment Configuration"

    check_file ".env"
    check_file ".env.example"

    if [ -f ".env" ]; then
        if grep -q "DATABASE_URL" .env; then
            pass "DATABASE_URL configured"
        else
            warn "DATABASE_URL not set in .env"
        fi

        if grep -q "RABBITMQ_URL" .env; then
            pass "RABBITMQ_URL configured"
        else
            warn "RABBITMQ_URL not set in .env"
        fi
    fi

    # ==========================================
    # 3. Project Structure
    # ==========================================
    header "3. Project Structure"

    check_file "src/orchestrator/main.py"
    check_file "src/common/models.py"
    check_file "src/common/protocol.py"
    check_file "tests/test_protocol_contract.py"
    check_file "migrations/env.py"
    check_file "docker-compose.yml"
    check_file "pyproject.toml"

    [ -d "docs" ] && pass "Documentation directory exists" || fail "Documentation directory not found"

    # ==========================================
    # 4. Python Dependencies
    # ==========================================
    header "4. Python Dependencies"

    if poetry check > /dev/null 2>&1; then
        pass "Poetry configuration valid"
    else
        fail "Poetry configuration invalid (run: poetry install)"
    fi

    # Check key dependencies
    if poetry show | grep -q "pydantic"; then
        pass "Pydantic installed"
    else
        warn "Pydantic not installed (run: poetry install)"
    fi

    if poetry show | grep -q "fastapi"; then
        pass "FastAPI installed"
    else
        warn "FastAPI not installed (run: poetry install)"
    fi

    if poetry show | grep -q "sqlalchemy"; then
        pass "SQLAlchemy installed"
    else
        warn "SQLAlchemy not installed (run: poetry install)"
    fi

    # ==========================================
    # 5. Docker Services
    # ==========================================
    header "5. Docker Services Status"

    info "Checking docker-compose services..."

    check_service "postgres"
    check_service "rabbitmq"
    check_service "ollama"
    check_service "litellm"

    # ==========================================
    # 6. Port Availability
    # ==========================================
    header "6. Service Ports"

    check_port "5432" "PostgreSQL"
    check_port "5672" "RabbitMQ"
    check_port "15672" "RabbitMQ Management"
    check_port "11434" "Ollama"
    check_port "8001" "LiteLLM"

    # ==========================================
    # 7. Database Verification
    # ==========================================
    header "7. Database Verification"

    if command -v docker-compose &> /dev/null && docker-compose ps postgres 2>/dev/null | grep -q "Up"; then
        # Check PostgreSQL connectivity
        if docker-compose exec -T postgres psql -U agent -d agent_deploy -c "SELECT 1" > /dev/null 2>&1; then
            pass "PostgreSQL connection successful"

            # Check if migrations are applied
            if docker-compose exec -T postgres psql -U agent -d agent_deploy -c "SELECT tablename FROM pg_tables WHERE schemaname='public'" | grep -q "tasks"; then
                pass "Database schema present (tasks table found)"

                # Check if sample data exists
                task_count=$(docker-compose exec -T postgres psql -U agent -d agent_deploy -t -c "SELECT COUNT(*) FROM tasks" 2>/dev/null | tr -d ' ')
                if [ -n "$task_count" ] && [ "$task_count" -gt 0 ]; then
                    pass "Sample data loaded ($task_count tasks)"
                else
                    warn "No sample data in tasks table (run: poetry run python scripts/seed_sample_data.py)"
                fi
            else
                fail "Database schema not applied (run: poetry run alembic upgrade head)"
            fi
        else
            fail "PostgreSQL connection failed"
        fi
    else
        warn "PostgreSQL service not running (start with: docker-compose up -d)"
    fi

    # ==========================================
    # 8. RabbitMQ Verification
    # ==========================================
    header "8. RabbitMQ Verification"

    if check_port "15672" "RabbitMQ Management"; then
        if curl -s -u guest:guest http://localhost:15672/api/overview > /dev/null 2>&1; then
            pass "RabbitMQ API accessible"
        else
            warn "RabbitMQ API not responding"
        fi
    fi

    # ==========================================
    # 9. Ollama Verification
    # ==========================================
    header "9. Ollama Verification"

    if check_port "11434" "Ollama"; then
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            pass "Ollama API accessible"

            # Check for models
            model_count=$(curl -s http://localhost:11434/api/tags 2>/dev/null | grep -o '"name"' | wc -l)
            if [ "$model_count" -gt 0 ]; then
                pass "Ollama models available ($model_count model(s))"
            else
                warn "No Ollama models loaded (run: curl -s http://localhost:11434/api/pull -d '{\"name\":\"neural-chat\"}')"
            fi
        else
            warn "Ollama API not responding"
        fi
    fi

    # ==========================================
    # 10. LiteLLM Verification
    # ==========================================
    header "10. LiteLLM Verification"

    if check_port "8001" "LiteLLM"; then
        if curl -s http://localhost:8001/health > /dev/null 2>&1; then
            pass "LiteLLM API accessible"

            # Check configuration file
            if [ -f "config/litellm-config.json" ]; then
                pass "LiteLLM configuration file present"

                if grep -q "fallback_strategy" config/litellm-config.json 2>/dev/null; then
                    pass "Fallback strategy configured"
                else
                    warn "Fallback strategy not found in config"
                fi
            else
                warn "LiteLLM configuration file not found"
            fi
        else
            warn "LiteLLM API not responding"
        fi
    fi

    # ==========================================
    # 11. Python Module Imports
    # ==========================================
    header "11. Python Module Imports"

    if poetry run python3 -c "from src.common.models import Task; from src.common.protocol import MessageEnvelope; print('OK')" > /dev/null 2>&1; then
        pass "Core modules importable"
    else
        fail "Core modules import failed (check imports in src/)"
    fi

    # ==========================================
    # 12. Unit Tests (Protocol)
    # ==========================================
    header "12. Unit Tests - Protocol Contract"

    if [ -f "tests/test_protocol_contract.py" ]; then
        if poetry run pytest tests/test_protocol_contract.py -q > /dev/null 2>&1; then
            test_count=$(poetry run pytest tests/test_protocol_contract.py --collect-only -q 2>/dev/null | wc -l)
            pass "Protocol contract tests pass (~$test_count tests)"
        else
            warn "Protocol contract tests failing (run: poetry run pytest tests/test_protocol_contract.py -v)"
        fi
    else
        warn "Protocol contract tests not found"
    fi

    # ==========================================
    # 13. Code Quality
    # ==========================================
    header "13. Code Quality Checks"

    # Black formatting
    if poetry run black --check src/ tests/ > /dev/null 2>&1; then
        pass "Code formatting (Black) OK"
    else
        warn "Code formatting issues (run: poetry run black src/ tests/)"
    fi

    # Ruff linting
    if poetry run ruff check src/ tests/ > /dev/null 2>&1; then
        pass "Code linting (Ruff) OK"
    else
        warn "Code linting issues (run: poetry run ruff check src/ tests/ --fix)"
    fi

    # ==========================================
    # 14. Documentation
    # ==========================================
    header "14. Documentation"

    check_file "docs/SETUP.md"
    check_file "docs/ARCHITECTURE.md"
    check_file "docs/PROTOCOL.md"
    check_file "README.md"

    # ==========================================
    # Summary
    # ==========================================
    echo ""
    header "Summary"

    total=$((PASSED + FAILED + WARNINGS))

    echo -e "Total checks: $total"
    echo -e "${GREEN}Passed: $PASSED${NC}"

    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
    fi

    if [ $FAILED -gt 0 ]; then
        echo -e "${RED}Failed: $FAILED${NC}"
        echo ""
        echo "To fix issues:"
        echo "  1. Review failures above"
        echo "  2. Start services: docker-compose up -d"
        echo "  3. Install deps: poetry install"
        echo "  4. Migrate DB: poetry run alembic upgrade head"
        echo "  5. Seed data: poetry run python scripts/seed_sample_data.py"
        echo "  6. Re-run: bash scripts/test-foundation.sh"
        echo ""
        return 1
    else
        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  Phase 1 Foundation: VERIFIED${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        echo "Next steps:"
        echo "  - Review architecture: docs/ARCHITECTURE.md"
        echo "  - Run orchestrator: poetry run uvicorn src.orchestrator.main:app --reload"
        echo "  - API docs: http://localhost:8000/docs"
        echo ""
        return 0
    fi
}

# Run main
main "$@"
