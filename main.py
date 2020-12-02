from ledpanel import PanelDriver
from nmigen import *
from nmigen.build import *
from platform.icebreaker import ICEBreakerPlatformCustom, PLL40, SinglePortMemory
from painters.address_test import CycleAddrTest
from painters.fluid_sim import Painter, Framebuffer, FluidSim
import argparse
from typing import Optional

# range 0-2, 3 means use the fancy painter
TEST_CYCLES = 3

class ResetLogic(Elaboratable):
    def __init__(self, button, led):
        self.button = button
        self.led = led
        self.button_rst_out = Signal()

    def elaborate(self, platform):
        m = Module()

        button_high_cycles = int(platform.default_clk_frequency * 0.05)
        button_high_cnt = Signal(range(button_high_cycles + 1))
        was_low = Signal()

        heartbeat = Signal()
        heartbeat_counter = Signal(range(int(platform.default_clk_frequency / 2 + 1)))

        m.d.sync += heartbeat_counter.eq(heartbeat_counter + 1)
        m.d.comb += heartbeat.eq(heartbeat_counter[-1])
        m.d.comb += platform.request('led', 2).eq(heartbeat)

        with m.If(self.button):
            with m.If(button_high_cnt == button_high_cycles):
                m.d.sync += self.button_rst_out.eq(1)
                m.d.sync += button_high_cnt.eq(0)
                m.d.sync += was_low.eq(0)
            with m.Else():
                with m.If(was_low):
                    m.d.sync += button_high_cnt.eq(button_high_cnt + 1)
        with m.Else():
            m.d.sync += button_high_cnt.eq(0)
            m.d.sync += was_low.eq(1)
            with m.If(button_high_cnt == 0):
                m.d.sync += self.button_rst_out.eq(0)
            with m.Else():
                m.d.sync += button_high_cnt.eq(button_high_cnt + 1)

        m.d.comb += self.led.eq(self.button_rst_out)

        return m

class HighSpeedLogic(Elaboratable):
    """
    This module contians all the logic that runs in the "high speed" (pixel
    clock) domain.
    """

    def __init__(self):
        self.o_frame = Signal(12)
        self.o_subframe = Signal(8)
        self.o_rgb0 = Signal(3)
        self.o_rgb1 = Signal(3)
        self.o_sclk = Signal(2)
        self.o_addr = Signal(5)
        self.o_blank = Signal(2)
        self.o_latch = Signal(2)
        self.o_rdy = Signal(1)

    def ports(self):
        return [
            self.o_frame,
            self.o_subframe,
            self.o_rgb0,
            self.o_rgb1,
            self.o_sclk,
            self.o_addr,
            self.o_blank,
            self.o_latch,
            self.o_rdy,
        ]

    def elaborate(self, platform):
        m = Module()

        if TEST_CYCLES <= CycleAddrTest.MAX_TEST_CYCLES:
            driver = PanelDriver(TEST_CYCLES)
            painter0 = CycleAddrTest(TEST_CYCLES, driver, side=0)
            painter1 = CycleAddrTest(TEST_CYCLES, driver, side=1)
        else:
            driver = PanelDriver(Painter.LATENCY)
            m.submodules.framebuffer0 = framebuffer0 = Framebuffer()
            m.submodules.framebuffer1 = framebuffer1 = Framebuffer()
            painter0 = Painter(driver, side=0, framebuffer=framebuffer0)
            painter1 = Painter(driver, side=1, framebuffer=framebuffer1)
            m.submodules.fluidsim = FluidSim(painter0, painter1)

        m.submodules.driver = driver
        m.submodules.painter0 = painter0
        m.submodules.painter1 = painter1

        # Bind passthrough outputs from the driver
        for (sport, oport) in zip(self.ports(), driver.panel_output_ports()):
            assert sport.width == oport.width

            m.d.comb += sport.eq(oport)

        return m

class BoardMapping(Elaboratable):
    def __init__(self, for_verilator: bool):
        self.for_verilator = for_verilator

    def elaborate(self, platform):
        m = Module()

        # Request resources from the platform
        panel = platform.request('led_panel', 0, xdr={
            'sclk': 2,
            'latch': 2,
            'blank': 2,
        })

        led_v = platform.request('led', 0)
        led_r = platform.request('rgb_led', 0).r

        button = platform.request('button', 0)
        led = Signal()

        m.d.comb += led_v.eq(led)
        m.d.comb += led_r.eq(led)

        reset_led = platform.request('led', 6)

        # Bind the high-speed clock domain and all logic from that domain
        m.submodules.pll40 = pll40 = PLL40(self.for_verilator)
        m.domains += pll40.domain
        dr = DomainRenamer(pll40.domain.name)

        logic = HighSpeedLogic()
        m.submodules.logic = dr(logic)

        # Add a register for the RGB outputs and addrs to synchronize with the DDR outputs
        delay_sigs = Cat(logic.o_rgb0, logic.o_rgb1, logic.o_addr)
        delayed_sigs = Cat(panel.rgb0, panel.rgb1, panel.addr)
        delay_sigs_ff = Signal.like(delay_sigs)
        m.d.hsclock += delay_sigs_ff.eq(delay_sigs)

        # Bind I/Os
        m.d.comb += [
            delayed_sigs.eq(delay_sigs_ff),
            # panel.addr.eq(driver.o_addr),
            Cat(panel.blank.o0, panel.blank.o1).eq(logic.o_blank),
            Cat(panel.latch.o0, panel.latch.o1).eq(logic.o_latch),
            Cat(panel.sclk.o0, panel.sclk.o1).eq(logic.o_sclk),

            panel.blank.o_clk.eq(pll40.domain.clk),
            panel.latch.o_clk.eq(pll40.domain.clk),
            panel.sclk.o_clk.eq(pll40.domain.clk),
        ]

        # Bind reset logic
        m.submodules.reset_mod = reset_mod = ResetLogic(button, led)
        m.d.comb += pll40.domain.rst.eq(reset_mod.button_rst_out | ResetSignal("sync") | ~pll40.locked)
        m.d.comb += reset_led.eq(pll40.domain.rst)

        return m

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    p_action = parser.add_subparsers(dest="action")
    p_action.add_parser("simulate")
    p_action.add_parser("verilog")
    p_action.add_parser("program")

    args = parser.parse_args()

    p = ICEBreakerPlatformCustom()
    p.add_resources(p.break_off_pmod)
    p.add_resources(p.led_panel_pmod)

    if args.action == "simulate":
        from nmigen.back import cxxrtl
        clk_freq = 1e6

        m = Module()

        with open('/home/bob_twinkles/Code/fpga/tools-venv/share/yosys/ice40/cells_sim.v') as cells_sim:
            p.add_file('cells-sim.v', cells_sim)

        m.submodules.logic = logic = HighSpeedLogic()

        ports = logic.ports()

        with open('blinker.cpp', 'w') as outf:
            outf.write(cxxrtl.convert(m, platform=p, ports=ports))

    if args.action == "program":
        p.build(BoardMapping(False), do_program=True)

    if args.action == "verilog":
        from nmigen.back import verilog
        with open('top_icebreaker.v', 'w') as outf:
            outf.write(verilog.convert(BoardMapping(True), platform=p, ports=[ClockSignal(), ResetSignal()]))
