# Python Code Style Pattern

Follow these patterns for consistent, maintainable Python:

## Type Hints
```python
# Good
def process_task(task_id: str, timeout: int) -> dict[str, Any]:
    """Process a task with given timeout."""
    pass

# Bad
def process_task(task_id, timeout):
    pass
```

## Docstrings
```python
# Good - describe what, args, returns, raises
def validate_yaml(content: str) -> bool:
    """Validate YAML content against task schema.

    Args:
        content: YAML string to validate

    Returns:
        True if valid, False otherwise

    Raises:
        yaml.YAMLError: If content is not parseable YAML
    """
    pass

# Bad - vague or missing
def validate_yaml(content):
    # checks if yaml is ok
    pass
```

## Imports
- Group: stdlib, third-party, local
- Alphabetical within groups
- One per line unless importing from same module

```python
import json
import yaml
from pathlib import Path
from typing import Any, Dict, List

import httpx

from chiffon.skills import SkillsRegistry
from src.common import logger
```

## Naming
- Functions/variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_`
