# Git Workflow Pattern

For task execution and reporting:

## Branch Naming
```
chiffon/<task-id>/<timestamp>
chiffon/task-3/20260202-204837
```

## Commit Messages
```
feat: add timeout validation

- Parse timeout from YAML
- Validate range 30-3600 seconds
- Report errors consistently

Closes: task-3 (subtask 1/3)
```

## Push and Tag
After successful execution:
```bash
git push origin chiffon/<task-id>/<timestamp>
git tag -a task-<id>-done -m "Completed: <goal>"
git push origin task-<id>-done
```

## Reporting Back
Include in Gitea issue comment:
```
✓ COMPLETED

Branch: chiffon/task-3/20260202-204837
Commit: abc1234
Tag: task-3-done

Verification results:
- pytest: PASSED
- lint: PASSED
```
