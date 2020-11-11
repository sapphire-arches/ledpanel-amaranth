from .utils import *
from nmigen import *
from nmigen.asserts import *

from ledpanel import PanelMux


class PanelMuxSpec(Elaboratable):
    def __init__(self):
        pass

    def elaborate(self, platform):
        m = Module()

        i0 = Signal(PanelMux.PANEL_WIDTH)
        i1 = Signal(PanelMux.PANEL_WIDTH)
        sel = Signal()

        m.submodules.dut = dut = PanelMux(sel, i0, i1)

        m.d.comb += i0.eq(AnyConst(PanelMux.PANEL_WIDTH))
        m.d.comb += i1.eq(AnyConst(PanelMux.PANEL_WIDTH))
        m.d.comb += sel.eq(AnyConst(1))
        with m.If(sel):
            m.d.comb += Assert(dut.o == i1)
        with m.Else():
            m.d.comb += Assert(dut.o == i0)

        return m

class MuxTest(FHDLTestCase):
    def test_mux(self):
        self.assertFormal(PanelMuxSpec(), mode="bmc", depth=2)
