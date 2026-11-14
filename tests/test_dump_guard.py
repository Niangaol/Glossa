"""写盘守卫：不做静默覆盖。"""

import pytest

from papertrace.schema_validate import dump_trace, minimal_trace
from tests._tmp import scratch_dir


def test_dump_refuses_existing_file_by_default():
    target = scratch_dir("dump-guard") / "trace.json"
    doc = minimal_trace(repo_url="x")
    dump_trace(doc, target)
    assert target.is_file()

    with pytest.raises(FileExistsError):
        dump_trace(doc, target)


def test_dump_overwrites_only_when_asked():
    target = scratch_dir("dump-force") / "trace.json"
    doc = minimal_trace(repo_url="x")
    dump_trace(doc, target)
    target.write_text("sentinel", encoding="utf-8")
    dump_trace(doc, target, overwrite=True)
    assert "sentinel" not in target.read_text(encoding="utf-8")
