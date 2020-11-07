#include <iostream>
#include <fstream>

#include <backends/cxxrtl/cxxrtl_vcd.h>

#include "./blinker.cpp"

int main(int argc, const char ** argv) {
  cxxrtl_design::p_top top;

  cxxrtl::debug_items all_debug_items;

  top.debug_info(all_debug_items);

  cxxrtl::vcd_writer vcd;
  vcd.timescale(1, "us");

  vcd.add_without_memories(all_debug_items);

  std::ofstream waves("waves.vcd");

  top.step();

  vcd.sample(0);

  top.p_rst.set<bool>(true);
  // top.p_i__rgb0.set(0b001u);
  // top.p_i__rgb1.set(0b001u);

  for (int steps = 0; steps <= 100000; ++steps) {
    top.p_clk.set<bool>(false);
    top.step();
    vcd.sample(steps * 2 + 0);

    top.p_clk.set<bool>(true);
    top.step();
    vcd.sample(steps * 2 + 1);

    if (steps > 300) {
      top.p_rst.set<bool>(false);
    }

    waves << vcd.buffer;
    vcd.buffer.clear();
  }
}
