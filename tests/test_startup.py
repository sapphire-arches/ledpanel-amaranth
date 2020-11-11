from .utils import *
from nmigen import *
from nmigen.sim import *
from nmigen.asserts import *
from unittest import TestCase

from ledpanel import FM6126StartupDriver, PanelMux

def panel_signal(rgb0, rgb1, addr, blank, latch, sclk):
    return rgb0 | (rgb1 << 3) | (addr << 6) | (blank << (6 + 5)) | (latch << (6 + 5 + 2)) | (sclk << (6 + 5 + 2 + 2))

class FM6126StartupDriverCase(TestCase):
    def test_startup_sequence(self):
        panel = Signal(PanelMux.PANEL_WIDTH)
        dut = FM6126StartupDriver(panel)
        dut_wrapper = PanelMux(0, dut.panel, Const(1, PanelMux.PANEL_WIDTH))

        def testbench():
            # Mask that selects only the metadata parts of the panel output field
            meta_only = panel_signal(0, 0, 0, 0b11, 0b11, 0b11)

            # Wait for startup
            self.assertEqual((yield dut.panel), panel_signal(0, 0, 0, 0b11, 0b00, 0b00))
            for i in range(2):
                yield

            for i in range(64):
                if i % 16 == 0:
                    expected_val = 0b000
                else:
                    expected_val = 0b111

                if i >= 53:
                    expected_latch = 0b11
                else:
                    expected_latch = 0b00

                v = yield dut.panel
                t = panel_signal(expected_val, expected_val, 0, 0b11, expected_latch, 0b10)
                self.assertEqual(v, t,
                    "Assertion on frame {}|{:017b} {:017b}".format(i, v, t)
                )
                vv = yield dut_wrapper.o
                self.assertEqual(v, vv,
                    "Assertion on frame {}|{:017b} {:017b}".format(v, vv, t)
                )
                yield

            # Go idle for 1 cycle
            v = (yield dut.panel) & meta_only
            t = panel_signal(0, 0, 0, 0b11, 0b00, 0b00)
            self.assertEqual(v, t,
                "Assertion on frame {}|{:017b} {:017b}".format(5, v, t)
            )
            yield

            for i in range(64):
                if (i % 16) == 9:
                    e_val = 0b111
                else:
                    e_val = 0b000

                if i >= 52:
                    e_latch = 0b11
                else:
                    e_latch = 0b00

                v = yield dut.panel
                expected = panel_signal(e_val, e_val, 0, 0b11, e_latch, 0b10)
                self.assertEqual(v, expected,
                    "Assertion on frame {}|{:017b} {:017b}".format(i + 65, v, expected)
                )
                yield

        root_mod = Module()
        root_mod.submodules.dut = dut
        root_mod.submodules.dut_wrapper = dut_wrapper

        simulator = Simulator(root_mod)
        simulator.add_clock(1e-6)
        simulator.add_sync_process(testbench)
        simulator.run()
