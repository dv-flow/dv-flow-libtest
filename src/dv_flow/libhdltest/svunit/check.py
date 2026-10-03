"""hdltest.svunit.Check: turn an SVUnit simulation log into an hdlsim.TestResult.

SVUnit exits 0 whether tests pass or fail, so the verdict comes from the log:
the test runner's last line, `INFO:  [t][testrunner]: PASSED (n of m suites
passing)`. Each failed check is an `ERROR: [t][<testcase>]: <msg> (at <file>
line:<n>)` line, which becomes a marker at that line of the unit-test file.
"""
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import SeverityE, TaskMarker, TaskMarkerLoc
from dv_flow.libhdlsim.sim_check import (
    _artifacts, _as_fileset, _case_name, _find_result, _locate_log, _maps)

_TEST = re.compile(r"^INFO:\s+\[\d+\]\[(\w+)\]: (\w+)::(PASSED|FAILED)\s*$")
_ERROR = re.compile(r"^ERROR:\s+\[\d+\]\[(\w+)\]: (.*?)(?: \(at (.+) line:(\d+)\))?\s*$")
_SUMMARY = re.compile(
    r"^INFO:\s+\[\d+\]\[(\w+)\]: (PASSED|FAILED) \((\d+) of (\d+) suites passing\)")


@dataclass
class Failure:
    testcase: str
    msg: str
    path: Optional[str] = None
    line: int = -1


@dataclass
class SvunitLog:
    passed: List[str] = field(default_factory=list)   # "testcase::test"
    failed: List[str] = field(default_factory=list)
    failures: List[Failure] = field(default_factory=list)
    summary: Optional[str] = None                     # "PASSED" / "FAILED" / None
    suites_passing: int = 0
    suites: int = 0


def parse_log(path: str) -> SvunitLog:
    out = SvunitLog()
    with open(path, errors="replace") as fp:
        for line in fp:
            line = line.rstrip("\n")
            m = _TEST.match(line)
            if m:
                (out.passed if m.group(3) == "PASSED" else out.failed).append(
                    f"{m.group(1)}::{m.group(2)}")
                continue
            m = _ERROR.match(line)
            if m:
                out.failures.append(Failure(
                    m.group(1), m.group(2), m.group(3),
                    int(m.group(4)) if m.group(4) else -1))
                continue
            m = _SUMMARY.match(line)
            if m:
                out.summary = m.group(2)
                out.suites_passing, out.suites = int(m.group(3)), int(m.group(4))
    return out


def verdict(log: SvunitLog, run_status: int) -> str:
    """pass / fail / error. `error` means the run never reached the runner's
    report (a crash, `$fatal`, or timeout), or exited nonzero after it."""
    if log.summary is None or run_status != 0:
        return "error"
    if log.summary == "PASSED" and not log.failed:
        return "pass"
    return "fail"


async def Check(ctxt, input) -> TaskDataResult:
    result = _find_result(input.inputs)
    if result is None:
        ctxt.error("svunit.Check: no hdlsim.SimRunResult input")
        return TaskDataResult(status=1)
    log_path = _locate_log(result, input.rundir)
    if log_path is None:
        ctxt.error("svunit.Check: simulation log not found")
        return TaskDataResult(status=1)

    run_status = getattr(result, "status", 0)
    log = parse_log(log_path)
    status = verdict(log, run_status)
    passed = status == "pass"
    gate = bool(input.params.gate)
    name = _case_name(input)

    sev = SeverityE.Error if (gate and not passed) else SeverityE.Info
    for f in log.failures:
        loc = TaskMarkerLoc(path=f.path, line=f.line) if f.path else None
        msg = f"{f.testcase}: {f.msg}"
        ctxt.add_marker(TaskMarker(severity=sev, msg=msg, loc=loc) if loc
                        else TaskMarker(severity=sev, msg=msg))
    if status == "error":
        ctxt.add_marker(TaskMarker(
            severity=sev,
            msg=f"SVUnit run did not complete (exit {run_status}, "
                f"{'no' if log.summary is None else 'a'} runner summary in {log_path})"))

    artifacts = [_as_fileset(a) for a in _artifacts(result)]
    xml = os.path.join(os.path.dirname(log_path), "tests.xml")
    if os.path.isfile(xml):
        artifacts.append(FileSet(src=input.name, filetype="junitXml",
                                 basedir=os.path.dirname(xml), files=["tests.xml"]))

    stats, runinfo = _maps(result)
    stats.update({"tests_passed": len(log.passed), "tests_failed": len(log.failed),
                  "tests_run": len(log.passed) + len(log.failed),
                  "suites": log.suites, "suites_passing": log.suites_passing})
    tr = ctxt.mkDataItem(
        "hdlsim.TestResult",
        testname=input.params.testname or "svunit", sim=getattr(result, "sim", ""),
        status=status, passed=passed, run_status=run_status,
        errors=len(log.failures), warnings=0, fatals=0,
        seed=int(runinfo.get("seed", 0) or 0),
        walltime_s=getattr(result, "walltime_s", 0.0),
        stats=stats, runinfo=runinfo, artifacts=artifacts)
    # `name` is reserved by mkDataItem; set it (and a distinct src, so a
    # suite's results are not deduplicated) after construction.
    tr.name = name
    tr.src = name

    ctxt.info(f"SVUnit {status}: {len(log.passed)} of "
              f"{len(log.passed) + len(log.failed)} tests passing")
    return TaskDataResult(status=1 if (gate and not passed) else 0, output=[tr])
