## Phase 8: End-to-End Integration Tests

tests/test_full_workflow_e2e.py validates the complete Chiffon workflow across phases 1-7. It exercises the dashboard API, orchestrator, infra agent, playbook analyzer, git audit, and audit services.

**Run all E2E tests:**
```bash
pytest tests/test_full_workflow_e2e.py -v
```

**Run by requirement:**
```bash
pytest tests/test_full_workflow_e2e.py -m e2e_01  # Full workflow tests
pytest tests/test_full_workflow_e2e.py -m e2e_02  # Config discovery tests
pytest tests/test_full_workflow_e2e.py -m e2e_03  # Execution tests
pytest tests/test_full_workflow_e2e.py -m e2e_04  # Audit trail tests
```

**Validate coverage:**
```bash
pytest tests/test_full_workflow_e2e.py --cov=src --cov-report=html
```
