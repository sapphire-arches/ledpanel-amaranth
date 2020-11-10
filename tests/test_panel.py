from .utils import *
from nmigen import *
from nmigen.asserts import *

from ledpanel import PanelDriver

class PanelDriverStartupSpec(Elaboratable):
    def __init__(self, test_latency):
        self.test_latency = test_latency

    def elaborate(self, platform):
        m = Module()

        dut = PanelDriver(self.test_latency)
        m.submodules.dut = dut

        counter = Signal(range(dut.startup_cycles() + 1))

        # Assuming reset is never asserted, once the driver is ready it should
        # never be unready. This is relied upon by all the other tests in this
        # module.
        m.d.comb += ResetSignal().eq(0) # ~Initial())
        with m.If(Past(dut.o_rdy, 1) == 1):
            m.d.comb += Assert(dut.o_rdy == 1)

        # with m.If(Initial()):
        #     m.d.comb += Assume(wait_for_startup.ongoing("START"))

        return m

class PanelDriverOutputSpec(Elaboratable):
    def __init__(self, test_latency):
        self.test_latency = test_latency

    def elaborate(self, platform):
        m = Module()
        dut = PanelDriver(0)

        m.submodules.dut = dut

        pixel0 = Signal(3)
        pixel1 = Signal(3)

        m.d.comb += ResetSignal().eq(~Initial())

        m.d.sync += pixel0.eq(AnyConst(3))
        m.d.sync += pixel1.eq(AnyConst(3))

        m.d.comb += dut.i_rgb0.eq(pixel0)
        m.d.comb += dut.i_rgb1.eq(pixel1)

        with m.If((dut.o_rdy == 1) & (dut.o_sclk == 0b10)):
            m.d.sync += Assert(dut.o_rgb0 == Past(pixel0, self.test_latency))
            m.d.sync += Assert(dut.o_rgb1 == Past(pixel1, self.test_latency))

        return m


class SimpleTest(FHDLTestCase):
    def test_startup(self):
        self.assertFormal(PanelDriverStartupSpec(0), mode="prove", depth=200)

    def test_output_0(self):
        self.assertFormal(PanelDriverOutputSpec(0), mode="prove", depth=200)

    def test_output_1(self):
        self.assertFormal(PanelDriverOutputSpec(1), mode="prove", depth=10)

    def test_output_2(self):
        self.assertFormal(PanelDriverOutputSpec(2), mode="prove", depth=10)
