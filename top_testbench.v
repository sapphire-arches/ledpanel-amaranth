`timescale 1ps/1ps

module top_tb();
  reg clk, rst;

  top top(rst, clk);

  initial begin
    $dumpfile("icarus-sim.vcd");
    $dumpvars(0, top_tb);
  end

  always #3333 clk = ~clk;

  initial begin
    clk = 0;
    rst = 1;

    #40000 rst = 0;

    #400000000 $finish;
  end
endmodule
