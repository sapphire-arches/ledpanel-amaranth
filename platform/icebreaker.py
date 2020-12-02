from nmigen import *
from nmigen.build import *
from nmigen.vendor.lattice_ice40 import LatticeICE40Platform
from nmigen_boards.resources import *
from typing import Optional
import os
import subprocess


def LEDPanelPModResource(*args, conn0, conn1):
    """
    Creates a resource family compatible with the LED panel PMOD
    """
    io = []
    io.append(Subsignal("rgb0", Pins("1 2 3", dir="o", conn=conn0, assert_width=3)))
    io.append(Subsignal("rgb1", Pins("7 8 9", dir="o", conn=conn0, assert_width=3)))
    io.append(Subsignal("addr", Pins("1 2 3 4 10", dir="o", conn=conn1, assert_width=5)))
    io.append(Subsignal("blank", Pins("7", dir="o", conn=conn1, assert_width=1)))
    io.append(Subsignal("latch", Pins("8", dir="o", conn=conn1, assert_width=1)))
    io.append(Subsignal("sclk", Pins("9", dir="o", conn=conn1, assert_width=1)))

    return Resource.family(*args, default_name="led_panel", ios=io)

class ICEBreakerPlatformCustom(LatticeICE40Platform):
    device      = "iCE40UP5K"
    package     = "SG48"
    # default_clk = "clk12"
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

    # resource collection for the LED panel PMOD
    led_panel_pmod = [
        LEDPanelPModResource(0, conn0=("pmod", 0), conn1=("pmod", 1))
    ]

    def toolchain_program(self, products, name):
        iceprog = os.environ.get("ICEPROG", "iceprog")
        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call([iceprog, bitstream_filename])


class PLL40(Elaboratable):
    """
    Wrapper for the ICE40 PLL40 primitive.

    Parameters
    ----------
    for_verilator : bool
        True when generating code for a Verilator simulation. This bypasses
        instantiating a PLL40 module at all, and instead binds the outputs to
        the "sync" clock domain so simulation can proceed.

    Attributes
    ----------
    domain : ClockDomain
        The output clock domain from the PLL
    locked : Signal(1), output
        Signal which goes high when the PLL is locked. Anything in the domain
        under this PLL should be held in reset until this signal goes high.
    """
    def __init__(self, for_verilator: bool):
        self.for_verilator = for_verilator
        self.domain = ClockDomain('hsclock')
        self.locked = Signal()

    def elaborate(self, platform):
        m = Module()

        # Configure a PLL40 module for 30MHz operation, except in simulation
        # mode where we just juse the regular sync clock
        if self.for_verilator:
            m.d.comb += self.locked.eq(1)
            m.d.comb += self.domain.clk.eq(ClockSignal("sync"))
        else:
            hsclock_lock_o = Signal()

            m.submodules += Instance("SB_PLL40_PAD",
                        p_FEEDBACK_PATH="SIMPLE",
                        p_DIVR=0b0000,
                        p_DIVF=0b1001111,
                        p_DIVQ=0b101,
                        p_FILTER_RANGE=0b001,
                        i_PACKAGEPIN=platform.request("clk12"),
                        o_PLLOUTCORE=self.domain.clk,
                        o_LOCK=hsclock_lock_o,
                        i_RESETB=1,
                        i_BYPASS=0
                    )
            platform.add_clock_constraint(self.domain.clk, 30e6)
            m.d.sync += self.locked.eq(hsclock_lock_o)

        return m

class SinglePortMemory(Elaboratable):
    """ Memory blocks for the simulation

    Attributes
    ----------
    address : Signal(14), in
        Address to modify
    w_data : Signal(16), in
        Data to write. Written to the memory at ``address`` when ``rw`` is high.
    r_data : Signal(16), out
        Data from the memory. Only valid when ``rw`` is low.
    rw : Signal(1), in
        When 0b1, perform a write. Otherwise read data is valid.
    """

    def __init__(self):
        self.address = Signal(14)
        self.w_data = Signal(16)
        self.r_data = Signal(16)
        self.rw = Signal(1)

    def elaborate(self, platform):
        m = Module()

        m.submodules += Instance("SB_SPRAM256KA",
            i_ADDRESS=self.address,
            i_DATAIN=self.w_data,
            o_DATAOUT=self.r_data,
            i_CHIPSELECT=1,
            i_WREN=self.rw,
            i_CLOCK=ClockSignal(),
            i_POWEROFF=1,
            i_MASKWREN=0b1111,
            i_SLEEP=0,
            i_STANDBY=0,
        )

        return m
