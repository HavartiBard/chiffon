# YAML Validation Pattern

When validating YAML configuration files:

## Process
1. Always use `yaml.safe_load()` to parse - never use `yaml.load()`
2. Define expected schema/fields upfront
3. Validate each field with type checking
4. Return structured list of errors: `[(field_name, error_message), ...]`
5. Use descriptive error messages for users

## Example
```python
import yaml

def validate_task_yaml(content: str) -> list[tuple[str, str]]:
    errors = []
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return [("parse", str(e))]

    # Check required fields
    required = ["id", "goal"]
    for field in required:
        if field not in data:
            errors.append((field, f"Required field '{field}' missing"))

    # Validate types
    if "constraints" in data:
        if not isinstance(data["constraints"], dict):
            errors.append(("constraints", "Must be a dict"))

    return errors
```

## Testing
Always write tests for validation: test happy path, missing fields, invalid types, parse errors.
