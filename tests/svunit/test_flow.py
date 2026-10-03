"""hdltest.svunit end to end: dv-flow builds and runs SVUnit tests on Verilator."""
import os
import shutil
from pathlib import Path

import pytest
from dv_flow.mgr import SeverityE
from pytest_dfm import *  # noqa: F401,F403  (the dvflow fixture)

from dv_flow.libhdltest.svunit.lib import find_svunit

DATA = Path(__file__).parent / "data"
_HERE_PKGDIR = str(Path(__file__).resolve().parents[2])

needs_sim = pytest.mark.skipif(
    shutil.which("verilator") is None
    or find_svunit("", os.environ, _HERE_PKGDIR)[0] is None,
    reason="needs verilator on PATH and an SVUnit install")


def _flow(tmp_path, tests, gate):
    tests_yaml = "".join(f"""\
  - name: {name}
    uses: std.FileSet
    with: {{type: svunitTest, base: "{DATA}", include: ["{f}"]}}
""" for name, f in tests)
    body = f"""\
package:
  name: t
  imports: [hdlsim, hdlsim.vlt, hdltest.svunit]
  tasks:
  - name: svunit
    uses: hdltest.svunit.Lib
  - name: dut
    uses: std.FileSet
    with: {{type: systemVerilogSource, base: "{DATA}", include: [adder.sv]}}
{tests_yaml}  - name: runner
    uses: hdltest.svunit.TestRunner
    needs: [{", ".join(n for n, _ in tests)}]
  - name: img
    uses: hdlsim.vlt.SimImage
    needs: [svunit, dut, runner]
    with: {{top: [testrunner]}}
  - name: run
    uses: hdlsim.vlt.SimRun
    needs: [img]
    with: {{mode: test}}
  - name: check
    uses: hdltest.svunit.Check
    needs: [run]
    with: {{gate: {str(gate).lower()}}}
"""
    p = tmp_path / "flow.dv"
    p.write_text(body)
    return str(p)


@pytest.fixture(autouse=True)
def _svunit_install(monkeypatch):
    # The test's flow lives in tmp_path, not in an IVPM project, so point
    # Lib at the SVUnit this checkout found.
    found = find_svunit("", os.environ, _HERE_PKGDIR)[0]
    if found:
        monkeypatch.setenv("SVUNIT_INSTALL", found)


def _run(dvflow, tmp_path, tests, gate=False):
    markers, outputs = [], {}

    def listen(t, reason):
        if reason == "leave":
            markers.extend(t.result.markers)
            outputs[t.name] = t.output
    status, _ = dvflow.runFlow(_flow(tmp_path, tests, gate), "t.check", listener=listen)
    return status, markers, outputs


def _result(outputs):
    return next(o for o in outputs["t.check"].output
                if getattr(o, "type", None) == "hdlsim.TestResult")


@needs_sim
def test_passing_tests(dvflow, tmp_path):
    status, markers, outs = _run(dvflow, tmp_path, [("tests", "adder_unit_test.sv")])
    assert status == 0, markers
    tr = _result(outs)
    assert tr.passed and tr.status == "pass"
    assert (tr.stats["tests_run"], tr.stats["tests_passed"]) == (2, 2)
    assert any(getattr(a, "filetype", None) == "junitXml" for a in tr.artifacts)


@needs_sim
def test_failure_is_data_by_default(dvflow, tmp_path):
    status, markers, outs = _run(dvflow, tmp_path, [("tests", "adder_bad_unit_test.sv")])
    assert status == 0
    tr = _result(outs)
    assert not tr.passed and tr.status == "fail"
    assert (tr.stats["tests_passed"], tr.stats["tests_failed"]) == (1, 1)


@needs_sim
def test_gate_fails_at_the_failing_check(dvflow, tmp_path):
    status, markers, _ = _run(
        dvflow, tmp_path, [("tests", "adder_bad_unit_test.sv")], gate=True)
    assert status != 0
    errs = [m for m in markers if m.severity == SeverityE.Error and m.loc]
    assert errs, markers
    assert errs[0].loc.path.endswith("adder_bad_unit_test.sv")
    assert errs[0].loc.line == 30
    assert "fail_unless_equal" in errs[0].msg


@needs_sim
def test_one_suite_per_fileset(dvflow, tmp_path):
    status, markers, outs = _run(dvflow, tmp_path, [
        ("good", "adder_unit_test.sv"), ("bad", "adder_bad_unit_test.sv")])
    assert status == 0, markers
    tr = _result(outs)
    assert (tr.stats["suites"], tr.stats["suites_passing"]) == (2, 1)
    assert (tr.stats["tests_run"], tr.stats["tests_failed"]) == (4, 1)
