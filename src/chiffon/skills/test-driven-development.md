# Test-Driven Development Pattern

For any feature or bug fix, follow this cycle:

## The Cycle: RED → GREEN → REFACTOR

### RED: Write Failing Test
- Write ONE test showing desired behavior
- Test should fail immediately (feature doesn't exist)
- Be specific: test one behavior at a time

### GREEN: Minimal Implementation
- Write simplest code to pass the test
- Don't add extra features or refactoring yet
- Goal: make test pass, nothing more

### REFACTOR: Clean Up
- Only after test passes, improve code
- Remove duplication
- Improve names, extract helpers
- Keep test passing throughout

## Example
```python
# RED: Write test
def test_parses_task_yaml():
    yaml_str = "id: task-1\ngoal: Test task"
    task = parse_task(yaml_str)
    assert task.id == "task-1"

# GREEN: Minimal code
def parse_task(yaml_str: str):
    import yaml
    data = yaml.safe_load(yaml_str)
    return Task(id=data["id"], goal=data["goal"])

# REFACTOR: Add docstrings, type hints, etc.
```

## Never
- Skip the failing test step (you won't know what you're testing)
- Write code before the test
- Add features beyond what the test requires
