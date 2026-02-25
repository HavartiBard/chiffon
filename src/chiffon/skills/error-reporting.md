# Error Reporting Pattern

When reporting errors to users:

## Principles
1. **Be specific** - What field? What constraint violated?
2. **Be actionable** - Suggest how to fix
3. **Be consistent** - Use structured format
4. **Include context** - Show invalid value, expected range

## Format
```
ERROR in <field>: <problem>
  Expected: <description of valid values>
  Got: <actual value>
  Suggestion: <how to fix>
```

## Example
```python
def report_error(field: str, problem: str, expected: str, got: str):
    msg = f"""ERROR in {field}: {problem}
  Expected: {expected}
  Got: {got}
"""
    return msg

# Usage
print(report_error(
    "timeout",
    "Outside valid range",
    "30-3600 seconds",
    "5000"
))
```

## Code Example
```python
def validate_timeout(value):
    errors = []
    if not isinstance(value, int):
        errors.append(report_error(
            "timeout",
            "Invalid type",
            "integer",
            type(value).__name__
        ))
    elif value < 30 or value > 3600:
        errors.append(report_error(
            "timeout",
            "Outside valid range",
            "30-3600 seconds",
            str(value)
        ))
    return errors
```
