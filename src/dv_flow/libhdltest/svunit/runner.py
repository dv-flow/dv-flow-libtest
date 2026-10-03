"""hdltest.svunit.TestRunner: generate SVUnit's test suites and test runner.

This replaces what SVUnit's `runSVUnit`/`buildSVUnit` Perl scripts write
(`create_testsuite.pl`, `create_testrunner.pl`), so the build goes through
`hdlsim.<sim>.SimImage` instead of SVUnit's own simulator invocation. One test
suite per input fileset (runSVUnit makes one per directory).
"""
import os
import re

from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import SeverityE, TaskMarker

_UNIT_TEST = re.compile(r"^\s*module\s+(\w+_unit_test)\b", re.M)


def strip_comments(text: str) -> str:
    """Drop // and /* */ comments, keeping newlines so line numbers hold."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def unit_tests(path: str):
    """The `<name>_unit_test` modules declared in a file, in order."""
    with open(path) as fp:
        return _UNIT_TEST.findall(strip_comments(fp.read()))


def sv_ident(s: str) -> str:
    s = re.sub(r"\W", "_", s).strip("_") or "suite"
    return s if not s[0].isdigit() else "_" + s


def instance_name(module: str) -> str:
    return module[:-len("_unit_test")] + "_ut"


def testsuite_sv(module: str, name: str, tests) -> str:
    insts = [(t, instance_name(t)) for t in tests]
    out = [f"module {module};",
           "  import svunit_pkg::svunit_testsuite;",
           "",
           f"  string name = \"{name}\";",
           "  svunit_testsuite svunit_ts;",
           ""]
    out += [f"  {t} {i}();" for t, i in insts]
    out += ["", "  function void build();"]
    for _, i in insts:
        out += [f"    {i}.build();", f"    {i}.__register_tests();"]
    out += ["    svunit_ts = new(name);"]
    out += [f"    svunit_ts.add_testcase({i}.svunit_ut);" for _, i in insts]
    out += ["  endfunction", "", "  task run();", "    svunit_ts.run();"]
    out += [f"    {i}.run();" for _, i in insts]
    out += ["    svunit_ts.report();", "  endtask", "endmodule", ""]
    return "\n".join(out)


def testrunner_sv(module: str, suites, harness=()) -> str:
    """`suites` is a list of (module, instance); `harness` lists modules to
    instantiate beside them (a test bench the unit tests share)."""
    out = [f"module {module};",
           "  import svunit_pkg::svunit_testrunner;",
           "",
           f"  string name = \"{module}\";",
           "  svunit_testrunner svunit_tr;",
           ""]
    out += [f"  {h} u_{h}();" for h in harness]
    out += [f"  {m} {i}();" for m, i in suites]
    out += ["",
            "  initial begin",
            "    build();",
            "    run();",
            "    $finish();",
            "  end",
            "",
            "  function void build();",
            "    svunit_tr = new(name);"]
    for _, i in suites:
        out += [f"    {i}.build();", f"    svunit_tr.add_testsuite({i}.svunit_ts);"]
    out += ["  endfunction", "", "  task run();"]
    out += [f"    {i}.run();" for _, i in suites]
    out += ["    svunit_tr.report();", "  endtask", "endmodule", ""]
    return "\n".join(out)


def _write(path: str, text: str) -> bool:
    """Write `text` unless the file already holds it. True if it changed."""
    if os.path.isfile(path):
        with open(path) as fp:
            if fp.read() == text:
                return False
    with open(path, "w") as fp:
        fp.write(text)
    return True


async def TestRunner(ctxt, input) -> TaskDataResult:
    top = input.params.top or "testrunner"
    rundir = input.rundir
    os.makedirs(rundir, exist_ok=True)

    sources, generated, suites, seen = [], [], [], set()
    for fs in input.inputs:
        if getattr(fs, "type", None) != "std.FileSet" or fs.filetype != "svunitTest":
            continue
        tests = []
        for f in fs.files:
            path = os.path.join(fs.basedir, f)
            found = unit_tests(path)
            if not found:
                ctxt.add_marker(TaskMarker(
                    severity=SeverityE.Warning,
                    msg=f"no `module <name>_unit_test` in {path}"))
            tests += found
        if not tests:
            continue
        # The unit-test files compile as ordinary SV, with their own
        # directory on the include path (as runSVUnit does).
        sources.append(FileSet(
            src=fs.src, filetype="systemVerilogSource", basedir=fs.basedir,
            files=list(fs.files), incdirs=list(fs.incdirs) + ["."],
            defines=list(fs.defines)))
        ident = base = sv_ident(fs.src or "suite")
        n = 1
        while ident in seen:
            n += 1
            ident = f"{base}_{n}"
        seen.add(ident)
        module = f"{ident}_testsuite"
        generated.append((f"{module}.sv", testsuite_sv(module, fs.src or ident, tests)))
        suites.append((module, f"{ident}_ts"))

    if not suites:
        ctxt.add_marker(TaskMarker(
            severity=SeverityE.Error,
            msg="TestRunner: no unit tests -- give it svunitTest filesets "
                "declaring `module <name>_unit_test`"))
        return TaskDataResult(status=1, output=[])

    harness = [h for h in (input.params.harness or []) if h]
    generated.append((f"{top}.sv", testrunner_sv(top, suites, harness)))
    changed = bool(input.changed)
    for name, text in generated:
        changed |= _write(os.path.join(rundir, name), text)

    return TaskDataResult(status=0, changed=changed, output=sources + [
        FileSet(src=input.name, filetype="systemVerilogSource", basedir=rundir,
                files=[n for n, _ in generated])])
