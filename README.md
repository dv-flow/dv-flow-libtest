# dv-flow-libhdltest

dv-flow tasks for HDL unit-test frameworks. A framework's tests are built and run
by `hdlsim` (any simulator it supports). Their verdict is an `hdlsim.TestResult`, so
they roll up in an `hdlsim.SimSuiteReport` with every other test.

| Package | Framework |
|---|---|
| `hdltest.svunit` | [SVUnit](https://github.com/svunit/svunit) |

## SVUnit

Test files are unchanged SVUnit: each is a `module <name>_unit_test` using the usual
`` `SVTEST `` macros. The tasks replace SVUnit's `runSVUnit` script:

| Task | Does |
|---|---|
| `hdltest.svunit.Lib` | finds SVUnit and outputs `svunit_pkg.sv` (and its JUnit writer) as a `systemVerilogSource` fileset |
| `hdltest.svunit.TestRunner` | generates the test suites (one per `svunitTest` fileset) and the `testrunner` top, as `runSVUnit` would |
| `hdltest.svunit.Check` | reads the log of an `hdlsim` `SimRun`. It outputs an `hdlsim.TestResult`, puts markers at failing checks, and forwards SVUnit's `tests.xml` |

```yaml
- name: svunit
  uses: hdltest.svunit.Lib
- name: tests
  uses: std.FileSet
  with: {type: svunitTest, include: ["*_unit_test.sv"]}
- name: runner
  uses: hdltest.svunit.TestRunner
  needs: [tests]
- name: img
  uses: hdlsim.vlt.SimImage
  needs: [svunit, dut, runner]
  with: {top: [testrunner]}
- name: run
  uses: hdlsim.vlt.SimRun
  needs: [img]
  with: {mode: test}
- name: check
  uses: hdltest.svunit.Check
  needs: [run]
  with: {gate: true}
```

### Where SVUnit comes from

`Lib` looks for SVUnit in this order:
1. its `install` parameter;
2. `$SVUNIT_INSTALL`, SVUnit's own convention, so an existing installation works
   unchanged;
3. `$IVPM_PACKAGES/svunit`. This package's `ivpm.yaml` depends on SVUnit, pinned
   to a release, so `ivpm update` in any project that uses dv-flow-libhdltest
   fetches it there;
4. `packages/svunit` under the flow's root directory or any parent. This finds the
   IVPM copy even when the project's environment isn't loaded.

An explicit location (1 or 2) that isn't an SVUnit installation is an error. The
search never quietly falls through to a different copy.

### Verilator

Verilator v5.048 and later (5.050, 5.052) reject SVUnit's `svunit_testsuite` class with "Duplicate
declaration of VARSCOPE ... i__Vloopsize". Verilator 5.046 is fine. `Lib`'s
`verilator_compat` option (on by default) stages a copy of `svunit_base` with the
`foreach` loop variable in `report()` renamed, which changes no behaviour.

## Tests

```
pytest tests
```

The flow tests need `verilator` on `PATH` and an SVUnit install; they are skipped
otherwise.
