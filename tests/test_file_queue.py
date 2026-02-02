import pathlib
import yaml
from src.chiffon.queue.file_queue import load_task, TaskEdit, TaskVerify, Task


def create_tmp_yaml(tmp_path, content):
    p = tmp_path / "task.yml"
    p.write_text(content)
    return p


# 1. valid YAML
def test_load_valid(tmp_path):
    yaml_content = """
id: task-123
goal: "Do something"
edits:
  - op: write
    file: foo.txt
    text: hello
verify:
  - cmd: echo ok
"""
    p = create_tmp_yaml(tmp_path, yaml_content)
    t = load_task(p)
    assert t.id == "task-123"
    assert t.goal == "Do something"
    assert len(t.edits) == 1
    e = t.edits[0]
    assert isinstance(e, TaskEdit)
    assert e.op == "write"
    assert e.file == "foo.txt"
    assert e.text == "hello"
    assert len(t.verifies) == 1
    v = t.verifies[0]
    assert isinstance(v, TaskVerify)
    assert v.cmd == "echo ok"


# 2. missing id
def test_missing_id(tmp_path):
    yaml_content = """
goal: Just something
"""
    p = create_tmp_yaml(tmp_path, yaml_content)
    try:
        load_task(p)
    except ValueError as e:
        assert "missing required keys" in str(e)
    else:
        raise AssertionError("Expected ValueError for missing id")


# 3. invalid op
def test_invalid_op(tmp_path):
    yaml_content = """
id: t1
goal: Test
edits:
  - op: delete
    file: bar.txt
    text: hi
"""
    p = create_tmp_yaml(tmp_path, yaml_content)
    try:
        load_task(p)
    except ValueError as e:
        assert "edit.op must be 'append' or 'write'" in str(e)
    else:
        raise AssertionError("Expected ValueError for invalid op")
