from .utils import *
from amaranth import *
from amaranth.asserts import *

from ledpanel import PixelScanner

class PanelDriverStartupSpec(Elaboratable):
    def __init__(self):
        pass

    def elaborate(self, platform):
        m = Module()

        dut = PixelScanner(8)
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


class SimpleTest(FHDLTestCase):
    def test_startup(self):
        self.assertFormal(PanelDriverStartupSpec(), mode="prove", depth=10)
