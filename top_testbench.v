`timescale 1ns/1ns

module top_tb();
  reg clk, rst;

  top top(rst, clk);

  initial begin
    $dumpfile("verilator-sim.vcd");
    $dumpvars(0, top_tb);
  end

  always #33 clk = ~clk;

  initial begin
    clk = 0;
    rst = 1;

    #1000 rst = 0;

    #4000000 $finish;
  end
endmodule
