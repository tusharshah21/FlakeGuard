import io
import zipfile

from flakeguard.ingest import parse_junit, resolve


def junit_zip(cases):
    child = {"fail": "<failure/>", "skip": "<skipped/>", "pass": ""}
    body = "".join(f'<testcase classname="m" name="{n}">{child[o]}</testcase>' for n, o in cases)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pytest.xml", f'<testsuites><testsuite tests="{len(cases)}">{body}</testsuite></testsuites>')
    return buf.getvalue()


def test_resolve_precedence():
    assert resolve(["fail", "fail"]) == "fail"
    assert resolve(["pass", "fail"]) == "fail"   # passed, then teardown error
    assert resolve(["fail", "pass"]) == "fail"
    assert resolve(["pass"]) == "pass"
    assert resolve(["skip", "fail"]) == "fail"
    assert resolve(["fail", "skip"]) == "fail"
    assert resolve(["skip", "pass"]) == "pass"


def test_duplicates_collapse_deterministically_and_are_counted():
    rows, why, collapses = parse_junit(junit_zip([("a", "fail"), ("a", "fail"), ("b", "pass"), ("b", "fail"), ("c", "fail"), ("c", "pass"),
                                                  ("d", "pass"), ("e", "skip"), ("e", "fail"), ("f", "fail"), ("f", "skip"), ("g", "skip")]))
    assert why is None
    assert dict(rows) == {"m::a": "fail", "m::b": "fail", "m::c": "fail", "m::d": "pass", "m::e": "fail", "m::f": "fail"}  # g: skip-only, dropped
    assert dict(collapses) == {("fail", "fail"): 1, ("pass", "fail"): 1, ("fail", "pass"): 1, ("skip", "fail"): 1, ("fail", "skip"): 1}
