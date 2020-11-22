from .utils import *
from nmigen import *
from nmigen.asserts import *

from ledpanel import PixelScanner

class PanelDriverStartupSpec(Elaboratable):
    def __init__(self, test_latency):
        self.test_latency = test_latency

    def elaborate(self, platform):
        m = Module()

        dut = PixelScanner(self.test_latency, 8)
        m.submodules.dut = dut

        # counter = Signal(range(dut.startup_cycles() + 1))

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
        dut = PixelScanner(0, 8)

        m.submodules.dut = dut

        pixel0 = Signal(3)
        pixel1 = Signal(3)

        m.d.comb += ResetSignal().eq(0)
        # m.d.b += dut.i_rgb0.eq(dut.o_y0[0:3])

        with m.If(dut.o_sclk.any()):
            m.d.sync += Assert(Past(dut.o_y0, self.test_latency)[0:5] == dut.o_addr)
            m.d.sync += Assert(Past(dut.i_rgb0, 1) == dut.o_rgb0)
            m.d.sync += Assert(Past(dut.i_rgb1, 1) == dut.o_rgb1)

        return m


class SimpleTest(FHDLTestCase):
    def test_startup(self):
        self.assertFormal(PanelDriverStartupSpec(0), mode="prove", depth=10)

    def test_output_0(self):
        self.assertFormal(PanelDriverOutputSpec(0), mode="prove", depth=300)

    # def test_output_1(self):
    #     self.assertFormal(PanelDriverOutputSpec(1), mode="prove", depth=10)

    # def test_output_2(self):
    #     self.assertFormal(PanelDriverOutputSpec(2), mode="prove", depth=10)
