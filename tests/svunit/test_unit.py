"""hdltest.svunit pieces that need no simulator."""
import os
from pathlib import Path

import pytest

from dv_flow.libhdltest.svunit import check, lib, runner

DATA = Path(__file__).parent / "data"


def _fake_install(root: Path) -> Path:
    (root / "svunit_base").mkdir(parents=True)
    (root / "svunit_base" / "svunit_pkg.sv").write_text("package svunit_pkg; endpackage\n")
    return root


# -- finding SVUnit ---------------------------------------------------------

def test_param_wins_over_environment(tmp_path):
    a, b = _fake_install(tmp_path / "a"), _fake_install(tmp_path / "b")
    path, origin, err = lib.find_svunit(str(a), {"SVUNIT_INSTALL": str(b)}, "")
    assert (path, err) == (str(a), None) and "install" in origin


def test_svunit_install_is_used(tmp_path):
    b = _fake_install(tmp_path / "b")
    path, origin, _ = lib.find_svunit("", {"SVUNIT_INSTALL": str(b)}, "")
    assert path == str(b) and origin == "$SVUNIT_INSTALL"


def test_explicit_location_that_is_not_svunit_is_an_error(tmp_path):
    good = _fake_install(tmp_path / "packages" / "svunit")
    path, _, err = lib.find_svunit("", {"SVUNIT_INSTALL": str(tmp_path / "nope"),
                                        "IVPM_PACKAGES": str(good.parent)}, "")
    assert path is None and "SVUNIT_INSTALL" in err and "nope" in err


def test_ivpm_packages_then_parent_directories(tmp_path):
    pkgs = _fake_install(tmp_path / "proj" / "packages" / "svunit").parent
    path, origin, _ = lib.find_svunit("", {"IVPM_PACKAGES": str(pkgs)}, "")
    assert path == str(pkgs / "svunit") and origin == "IVPM"
    # No environment: found by walking up from the root package's directory.
    sub = tmp_path / "proj" / "examples" / "x"
    sub.mkdir(parents=True)
    path, _, _ = lib.find_svunit("", {}, str(sub))
    assert path == str(pkgs / "svunit")


def test_not_found_lists_where_it_looked(tmp_path):
    path, _, err = lib.find_svunit("", {}, str(tmp_path))
    assert path is None
    assert str(tmp_path / "packages" / "svunit") in err


def test_foreach_fix_renames_only_the_report_loop(tmp_path):
    inst = _fake_install(tmp_path / "s")
    src = (
        "function int unsigned get_num();\n"
        "  foreach (list_of_testcases[i])\n"
        "    if (list_of_testcases[i].get_results() == PASS) n++;\n"
        "endfunction\n"
        "function void svunit_testsuite::report();\n"
        "  foreach(list_of_testcases[i])\n"
        "    list_of_testcases[i].report();\n"
        "endfunction\n")
    (inst / "svunit_base" / "svunit_testsuite.sv").write_text(src)
    assert lib.needs_foreach_fix(str(inst))
    root = lib.stage_with_fix(str(inst), str(tmp_path / "run"))
    out = (Path(root) / "svunit_base" / "svunit_testsuite.sv").read_text()
    assert "foreach (list_of_testcases[j])\n    list_of_testcases[j].report();" in out
    assert "foreach (list_of_testcases[i])\n    if" in out
    assert not lib.needs_foreach_fix(root)


# -- generating the runner --------------------------------------------------

def test_unit_tests_ignores_commented_out_modules(tmp_path):
    f = tmp_path / "t.sv"
    f.write_text("// module old_unit_test;\n/* module gone_unit_test;\n*/\n"
                 "module a_unit_test; endmodule\nmodule helper; endmodule\n"
                 "  module b_unit_test #(); endmodule\n")
    assert runner.unit_tests(str(f)) == ["a_unit_test", "b_unit_test"]


def test_generated_suite_and_runner_match_svunit_shape():
    ts = runner.testsuite_sv("t_tests_testsuite", "t.tests", ["adder_unit_test"])
    assert "adder_unit_test adder_ut();" in ts
    assert "adder_ut.__register_tests();" in ts
    assert "svunit_ts.add_testcase(adder_ut.svunit_ut);" in ts
    tr = runner.testrunner_sv("testrunner", [("t_tests_testsuite", "t_tests_ts")])
    assert tr.startswith("module testrunner;")
    assert "svunit_tr.add_testsuite(t_tests_ts.svunit_ts);" in tr
    assert "$finish();" in tr
    assert "u_" not in tr


def test_harness_modules_are_instantiated_in_the_runner():
    tr = runner.testrunner_sv("testrunner", [("s_testsuite", "s_ts")], ["bench_harness"])
    assert "  bench_harness u_bench_harness();" in tr
    assert tr.index("u_bench_harness") < tr.index("s_testsuite s_ts")


def test_sv_ident():
    assert runner.sv_ident("ex.crc32.tests") == "ex_crc32_tests"
    assert runner.sv_ident("1st") == "_1st"


# -- reading the log --------------------------------------------------------

def test_passing_log():
    log = check.parse_log(str(DATA / "pass.log"))
    assert log.passed == ["adder_ut::adds", "adder_ut::wraps"] and not log.failed
    assert (log.summary, log.suites_passing, log.suites) == ("PASSED", 1, 1)
    assert check.verdict(log, 0) == "pass"


def test_failing_log_locates_the_check():
    log = check.parse_log(str(DATA / "fail.log"))
    assert log.failed == ["adder_ut::wraps"]
    (f,) = log.failures
    assert (f.testcase, f.path, f.line) == ("adder_ut", "/src/adder_unit_test.sv", 21)
    assert f.msg.startswith("fail_unless_equal:")
    assert check.verdict(log, 0) == "fail"


def test_run_that_never_reports_is_an_error():
    log = check.parse_log(str(DATA / "crash.log"))
    assert log.summary is None
    assert check.verdict(log, 0) == "error"
    # A nonzero exit after a PASSED report is not a pass either.
    assert check.verdict(check.parse_log(str(DATA / "pass.log")), 1) == "error"
