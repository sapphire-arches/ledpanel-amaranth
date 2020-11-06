from ledpanel import LEDBlinker, LEDForward
from nmigen import *
from nmigen.build import *
from nmigen.vendor.lattice_ice40 import *
from nmigen_boards.resources import *
import argparse
import os
import subprocess


class ICEBreakerPlatformCustom(LatticeICE40Platform):
    device      = "iCE40UP5K"
    package     = "SG48"
    default_clk = "SB_HFOSC"
    hfosc_div = 3

    resources   = [
        Resource("clk12", 0, Pins("35", dir="i"),
                 Clock(12e6), Attrs(GLOBAL=False, IO_STANDARD="SB_LVCMOS")),

        *LEDResources(pins="11 37", invert=True, attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        # Semantic aliases
        Resource("led_r", 0, PinsN("11", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 0, PinsN("37", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),

        RGBLEDResource(0, r="39", g="40", b="41", attrs=Attrs(IO_STANDARD="SB_LVCMOS")),

        *ButtonResources(pins="10", invert=True, attrs=Attrs(IO_STANDARD="SB_LVCMOS")),

        UARTResource(0,
            rx="6", tx="9",
            attrs=Attrs(IO_STANDARD="SB_LVTTL", PULLUP=1)
        ),

        *SPIFlashResources(0,
            cs="16", clk="15", copi="14", cipo="17", wp="12", hold="13",
            attrs=Attrs(IO_STANDARD="SB_LVCMOS")
        ),
    ]
    connectors = [
        Connector("pmod", 0, " 4  2 47 45 - -  3 48 46 44 - -"), # PMOD1A
        Connector("pmod", 1, "43 38 34 31 - - 42 36 32 28 - -"), # PMOD1B
        Connector("pmod", 2, "27 25 21 19 - - 26 23 20 18 - -"), # PMOD2
    ]
    # The attached LED/button section can be either used standalone or as a PMOD.
    # Attach to platform using:
    # p.add_resources(p.break_off_pmod)
    # pmod_btn = plat.request("user_btn")
    break_off_pmod = [
        *LEDResources(pins={2: "7", 3: "1", 4: "2", 5: "8", 6: "3"}, conn=("pmod", 2),
                      attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        # Semantic aliases
        Resource("led_r", 1, Pins("7", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 1, Pins("1", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 2, Pins("2", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 3, Pins("8", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 4, Pins("3", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),

        *ButtonResources(pins={1: "9", 2: "4", 3: "10"}, conn=("pmod", 2),
                         attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
    ]

    def toolchain_program(self, products, name):
        iceprog = os.environ.get("ICEPROG", "iceprog")
        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call([iceprog, bitstream_filename])


class BoardMapping(Elaboratable):
    def __init__(self, blinker):
        self.blinker = blinker
        self.fwd = LEDForward()

    def elaborate(self, platform):
        m = Module()

        led = platform.request("led")
        rgb_led = platform.request("rgb_led")

        m.d.comb += led.eq(self.blinker.o) # led.eq(self.blinker.o)
        m.d.comb += rgb_led.eq(self.blinker.o)

        cd_hsclock = ClockDomain()
        m.domains += cd_hsclock

        hsclock_lock = Signal()

        # Configure a PLL40 module for 30MHz operation
        m.submodules += Instance("SB_PLL40_PAD",
                    p_FEEDBACK_PATH="SIMPLE",
                    p_DIVR=0b0000,
                    p_DIVF=0b1001111,
                    p_DIVQ=0b101,
                    p_FILTER_RANGE=0b001,
                    i_PACKAGEPIN=platform.request("clk12"),
                    o_PLLOUTCORE=cd_hsclock.clk,
                    o_LOCK=hsclock_lock,
                    i_RESETB=1,
                    i_BYPASS=0
                )

        m.d.comb += cd_hsclock.rst.eq(ResetSignal("sync") & ~hsclock_lock)

        buttons = Cat(platform.request("button", 1), platform.request("button", 2), platform.request("button", 3))
        leds = Cat(platform.request("led", 3), platform.request("led", 2), platform.request("led", 4))

        m.d.comb += self.fwd.i.eq(buttons)
        m.d.comb += leds.eq(self.fwd.o)

        dr = DomainRenamer("hsclock")
        m.submodules.blinker = dr(self.blinker)
        m.submodules.fwd = dr(self.fwd)

        return m

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    p_action = parser.add_subparsers(dest="action")
    p_action.add_parser("simulate")
    p_action.add_parser("program")

    args = parser.parse_args()
    if args.action == "simulate":
        from nmigen.back import cxxrtl
        clk_freq = 1e6
        blinker = LEDBlinker(clk_freq)

        with open('blinker.cpp', 'w') as outf:
            outf.write(cxxrtl.convert(blinker))
    if args.action == "program":
        from nmigen_boards.icebreaker import *
        p = ICEBreakerPlatformCustom()
        p.add_resources(p.break_off_pmod)
        p.build(BoardMapping(), do_program=True)
