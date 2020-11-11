#include <algorithm>
#include <iostream>
#include <fstream>
#include <iomanip>

#include <backends/cxxrtl/cxxrtl_vcd.h>

#include "./blinker.cpp"

template<size_t Length>
class ShiftReg {
public:
  ShiftReg() :
    offset(0),
    prev_latch_line{false}
  {
    std::fill(input.begin(), input.end(), 0);
    std::fill(latched.begin(), latched.end(), 0);
  }

  ~ShiftReg() = default;

  ShiftReg(ShiftReg & other) = delete;
  ShiftReg(ShiftReg && other) = delete;

  ShiftReg & operator=(ShiftReg & other) = delete;
  ShiftReg & operator=(ShiftReg && other) = delete;

  void clock_in(uint8_t val) {
    input[offset] = val;
    offset = (offset + 1) % Length;
  }

  void set_latch(bool latch) {
    if (prev_latch_line && !latch) {
      // on falling edge, accept data
      std::copy(input.begin(), input.end(), latched.begin());
      // assert(offset == 0);
    }
    prev_latch_line = latch;
  }

  void clear_latched() {
    std::fill(latched.begin(), latched.end(), 0);
  }

  template<size_t Length0>
  friend std::ostream & operator<< (std::ostream & o, ShiftReg<Length0> & sr);

  uint32_t operator[] (size_t addr) {
    return latched[addr];
  }

private:
  std::array<uint8_t, Length> input;
  std::array<uint8_t, Length> latched;
  size_t offset;
  bool prev_latch_line;
};

template<size_t Length>
std::ostream & operator<<(std::ostream & o, ShiftReg<Length> & sr) {
  o << "REG ";

  size_t i = (sr.offset + (Length - 1)) % Length;
  while (i != sr.offset) {
    o << int(sr.latched[i]) << " ";
    i = (i + (Length - 1)) % Length;
  }

  return o;
}

template<size_t Rows, size_t Columns>
class Panel {
public:
  Panel() :
    frame{0}
  {
    std::fill(brightness.begin(), brightness.end(), 0);
  }

  ~Panel() = default;
  Panel(Panel & other) = delete;
  Panel(Panel && other) = delete;

  Panel & operator=(Panel & other) = delete;
  Panel & operator=(Panel && other) = delete;

  void brighness_tick(ShiftReg<Columns> * rows, size_t y) {
    y = Columns - y - 1;
    for (int i = 0; i < 3; ++i) {
      for (size_t x = 0; x < Rows; ++x) {
        brightness[(y * 64 + x) * 3 + i] += rows[i][x];
      }
    }
  }

  void on_next_frame() {
    if ((frame < 5) ||
        (30 <= frame && frame <= 33) ||
        (62 <= frame && frame <= 66)
        ) {
      std::cout << *this << std::endl;
    }

    frame++;

    this->clear();
  }

  void clear() {
    std::fill(brightness.begin(), brightness.end(), 0);
  }

  size_t frame;

  template<size_t R, size_t C>
  friend std::ostream & operator<<(std::ostream &, Panel<R, C> &);
private:
  std::array<uint32_t, Rows * Columns * 3> brightness;
};

template<size_t Rows, size_t Columns>
std::ostream & operator<<(std::ostream & o, Panel<Rows, Columns> & p) {
  o << "FRAME[" << p.frame << "]" << std::endl;
  o << std::hex;
  const uint32_t div = 0x10;

  o << "   ";
  for (size_t y = 0; y < Columns; ++y) {
    o << std::setw(6) << (Columns - y - 1);
  }
  o << std::endl;

  for (size_t x = 0; x < Rows; x++) {
    o << std::setw(2) << x << " ";
    for (size_t y = 0; y < Columns; ++y) {
      int idx = (y * 64 + x) * 3 + 1;

      o << std::setw(4) << int(p.brightness[idx] / div);
      if (p.brightness[idx] % div != 0) {
        o << "." << (p.brightness[idx] % div);
      } else {
        o << "  ";
      }
    }
    o << std::endl;
  }
  o << std::dec;
  return o;
}

int main(int argc, const char ** argv) {
  cxxrtl_design::p_top top;

  cxxrtl::debug_items all_debug_items;

  top.debug_info(all_debug_items, "top ");

  cxxrtl::vcd_writer vcd;
  vcd.timescale(1, "us");

  vcd.add_without_memories(all_debug_items);

  std::ofstream waves("waves.vcd");

  top.step();

  vcd.sample(0);

  top.p_rst.set<bool>(true);

  ShiftReg<64> display_chain[6];

  std::array<uint16_t, 64 * 64 * 3> accumulators;
  std::fill(accumulators.begin(), accumulators.end(), 0x0);

  Panel<64, 64> panel{};

  int steps = 0;
  uint32_t last_frame = uint32_t(-1);
  uint32_t last_subframe = uint32_t(-1);
  uint32_t last_addr = uint32_t(-1);
  uint32_t frame = uint32_t(-1);
  uint32_t addr = uint32_t(-1);
  uint32_t subframe = uint32_t(-1);
  uint32_t o_rdy_high = 0;
  while (top.p_o__frame.get<uint32_t>() < 3) {
    top.p_clk.set<bool>(true);
    top.step();

    // Sample the rising clock edge
    vcd.sample(steps * 2 + 0);
    addr = top.p_o__addr.get<uint32_t>();
    frame = top.p_o__frame.get<uint32_t>();
    subframe = top.p_o__subframe.get<uint32_t>();

    // If we have switched LED banks, dump shift register state
    if (addr != last_addr) {
      uint32_t subframe = top.p_o__subframe.get<uint32_t>();
      uint32_t frame = top.p_o__frame.get<uint32_t>();

      // if ((frame == 0 || frame == 1) && last_addr == frame) {
      //   std::cout << std::setw(3) << frame << "|" << std::setw(3) << subframe << "|" << std::setw(3) << last_addr << "|"
      //             << display_chain[1] << std::endl;
      // }
    }

    if (frame != last_frame) {
      panel.frame = frame;
      panel.on_next_frame();
    }
    last_frame = frame;

    if (o_rdy_high == 128) {
      panel.clear();
    }

    // Count the number of clocks o_rdy has been high for
    if (top.p_o__rdy.get<bool>()) {
      o_rdy_high++;
    }
    // std::cout << "NOT READY " << top.p_driver_2e_fsm__state.get<uint32_t>() << std::endl;

    if (subframe != last_subframe) {
      if (subframe == 0 && frame != panel.frame) {
        // panel.on_next_frame();
        // panel.frame = frame;
      }
      // std::cout << "STEPS[" << steps << "]" << "RUNNING[" << o_rdy_high << "]" << "SUBFRAME[" << subframe << "] " << panel << std::endl;
    }
    last_subframe = subframe;

    // Shift registers clock in on rising edge
    if (top.p_o__sclk.get<uint8_t>() == 0b10) {
      uint8_t rgb0 = top.p_o__rgb0.get<uint8_t>();
      uint8_t rgb1 = top.p_o__rgb1.get<uint8_t>();

      display_chain[0].clock_in(rgb0 & 0b001 ? 1 : 0);
      display_chain[1].clock_in(rgb0 & 0b010 ? 1 : 0);
      display_chain[2].clock_in(rgb0 & 0b100 ? 1 : 0);
      display_chain[3].clock_in(rgb1 & 0b001 ? 1 : 0);
      display_chain[4].clock_in(rgb1 & 0b010 ? 1 : 0);
      display_chain[5].clock_in(rgb1 & 0b100 ? 1 : 0);
    }

    // Rising edge is bit 0 of the latch output
    bool is_latch = (top.p_o__latch.get<uint8_t>() & 0b01) == 0b01;
    for (int i = 0; i < 6; ++i) {
      display_chain[i].set_latch(is_latch);
    }

    // accumulate brightness for the rising edge
    if (!(top.p_o__blank.get<uint8_t>() & 0b10)) {
      panel.brighness_tick(&display_chain[0], addr);
      panel.brighness_tick(&display_chain[3], addr + 32);
    }

    top.p_clk.set<bool>(false);
    top.step();

    // Sample the falling clock edge
    vcd.sample(steps * 2 + 1);
    addr = top.p_o__addr.get<uint32_t>();
    frame = top.p_o__frame.get<uint32_t>();
    subframe = top.p_o__subframe.get<uint32_t>();

    // Falling edge is bit 1 of the latch output
    is_latch = (top.p_o__latch.get<uint8_t>() & 0b10) == 0b10;
    for (int i = 0; i < 6; ++i) {
      display_chain[i].set_latch(is_latch);
    }

    // accumulate brightness for the falling edge
    if (!(top.p_o__blank.get<uint8_t>() & 0b01)) {
      panel.brighness_tick(&display_chain[0], addr);
      panel.brighness_tick(&display_chain[3], addr + 32);
    }

    last_addr = addr;

    // Deassert reset 10 steps into the simulation
    if (steps > 10) {
      top.p_rst.set<bool>(false);
      if (steps == 11) {
        panel.clear();
      }
    }

    // Dump waves
    waves << vcd.buffer;
    vcd.buffer.clear();
    steps++;
  }
}
