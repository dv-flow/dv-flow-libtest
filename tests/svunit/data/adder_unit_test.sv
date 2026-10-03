`include "svunit_defines.svh"

module adder_unit_test;
  import svunit_pkg::svunit_testcase;

  string name = "adder_ut";
  svunit_testcase svunit_ut;

  function void build();
    svunit_ut = new(name);
  endfunction

  task setup();
    svunit_ut.setup();
  endtask

  task teardown();
    svunit_ut.teardown();
  endtask

  `SVUNIT_TESTS_BEGIN

  `SVTEST(adds)
    `FAIL_UNLESS_EQUAL(adder_pkg::add(8'd2, 8'd3), 8'd5)
  `SVTEST_END

  // Takes simulated time, as a test against RTL would.
  `SVTEST(wraps_after_a_delay)
    #10;
    `FAIL_UNLESS_EQUAL(adder_pkg::add(8'd255, 8'd1), 8'd0)
  `SVTEST_END

  `SVUNIT_TESTS_END
endmodule
