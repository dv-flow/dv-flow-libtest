"""hdltest.svunit.Lib: find SVUnit and hand its sources to the simulator."""
import hashlib
import os
import re
import shutil

from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import SeverityE, TaskMarker

PKG = os.path.join("svunit_base", "svunit_pkg.sv")


def is_svunit(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, PKG))


def find_svunit(param: str, env, root_pkgdir: str):
    """Locate an SVUnit installation.

    Returns (path, origin, error). The search order is:

    1. the task's `install` parameter;
    2. `$SVUNIT_INSTALL` -- SVUnit's own convention (its Setup scripts set it),
       so an existing SVUnit install works unchanged;
    3. `$IVPM_PACKAGES/svunit` -- the copy IVPM fetches for any project that
       depends on dv-flow-libhdltest;
    4. `packages/svunit` in the root package's directory or any parent, for
       an IVPM project whose environment was not loaded.

    A location given explicitly (1 or 2) that is not an SVUnit install is an
    error, not a reason to look elsewhere: silently picking up a different
    copy is worse than failing.
    """
    for origin, path in (("the `install` parameter", param),
                         ("$SVUNIT_INSTALL", env.get("SVUNIT_INSTALL", ""))):
        if path:
            path = os.path.abspath(os.path.expanduser(path))
            if is_svunit(path):
                return path, origin, None
            return None, origin, f"{origin} is {path}, which has no {PKG}"

    tried = []
    if env.get("IVPM_PACKAGES"):
        tried.append(os.path.join(env["IVPM_PACKAGES"], "svunit"))
    d = os.path.abspath(root_pkgdir) if root_pkgdir else ""
    while d:
        tried.append(os.path.join(d, "packages", "svunit"))
        parent = os.path.dirname(d)
        d = parent if parent != d else ""
    for path in tried:
        if is_svunit(path):
            return path, "IVPM", None
    return None, None, (
        "SVUnit not found: set the `install` parameter or $SVUNIT_INSTALL, or "
        "add svunit to the project's ivpm.yaml. Looked in: " + ", ".join(tried))


# Verilator 5.050 and 5.052 (and 5.049-devel; 5.046 and 5.041 are fine) reject
# SVUnit's svunit_testsuite class: "Duplicate declaration of VARSCOPE
# 'svunit_pkg.svunit_testsuite.unnamedblk1.i__Vloopsize'". Its
# get_num_passing_testcases() and report() both loop `foreach
# (list_of_testcases[i])`; renaming report()'s loop variable avoids it. (A
# small class with the same two loops does not reproduce it, so the exact
# trigger is not isolated.) The rename is behaviour-preserving on every
# simulator.
_FOREACH_FIX = (
    re.compile(r"foreach\s*\(\s*list_of_testcases\[i\]\s*\)(\s*)"
               r"list_of_testcases\[i\]\.report\(\);"),
    r"foreach (list_of_testcases[j])\1list_of_testcases[j].report();")


def _testsuite_file(base: str) -> str:
    for n in ("svunit_testsuite.sv", "svunit_testsuite.svh"):
        if os.path.isfile(os.path.join(base, n)):
            return n
    return ""


def needs_foreach_fix(install: str) -> bool:
    base = os.path.join(install, "svunit_base")
    n = _testsuite_file(base)
    if not n:
        return False
    with open(os.path.join(base, n)) as fp:
        return bool(_FOREACH_FIX[0].search(fp.read()))


def stage_with_fix(install: str, rundir: str) -> str:
    """Copy svunit_base into `rundir` with the foreach rename applied.
    Returns the directory that now plays the role of the install."""
    dst = os.path.join(rundir, "svunit_base")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(install, "svunit_base"), dst)
    n = _testsuite_file(dst)
    p = os.path.join(dst, n)
    with open(p) as fp:
        text = fp.read()
    with open(p, "w") as fp:
        fp.write(_FOREACH_FIX[0].sub(_FOREACH_FIX[1], text))
    return rundir


def _stamp(install: str, fix: bool) -> str:
    st = os.stat(os.path.join(install, PKG))
    return hashlib.sha1(f"{install}|{st.st_mtime_ns}|{fix}".encode()).hexdigest()


async def Lib(ctxt, input) -> TaskDataResult:
    p = input.params
    install, origin, err = find_svunit(p.install, ctxt.env, ctxt.root_pkgdir or "")
    if install is None:
        ctxt.add_marker(TaskMarker(severity=SeverityE.Error, msg=err))
        return TaskDataResult(status=1, output=[])
    ctxt.info(f"SVUnit: {install} (from {origin})")

    rundir = input.rundir
    os.makedirs(rundir, exist_ok=True)
    fix = bool(p.verilator_compat) and needs_foreach_fix(install)
    stamp = _stamp(install, fix)
    stamp_file = os.path.join(rundir, "svunit.stamp")
    changed = True
    if os.path.isfile(stamp_file):
        with open(stamp_file) as fp:
            changed = fp.read() != stamp

    root = install
    if fix:
        if changed or not os.path.isdir(os.path.join(rundir, "svunit_base")):
            stage_with_fix(install, rundir)
        root = rundir
        ctxt.info("SVUnit: staged a copy with the Verilator foreach rename "
                  "(verilator_compat)")
    with open(stamp_file, "w") as fp:
        fp.write(stamp)

    return TaskDataResult(status=0, changed=changed, output=[
        FileSet(src=input.name, filetype="systemVerilogSource", basedir=root,
                files=["svunit_base/junit-xml/junit_xml.sv",
                       "svunit_base/svunit_pkg.sv"],
                incdirs=["svunit_base/junit-xml", "svunit_base"])])
