import unittest
import random

from .utils import *
from painters.util import XORShiftRandomizer
from nmigen import *
from nmigen.sim import *

class XORShiftRandomizerReference:
    def __init__(self, init, a, b, c):
        self.state = init
        self.mask = (1 << 64) - 1
        self.a = a
        self.b = b
        self.c = c

    def advance(self):
        self.state = ((self.state << self.a) ^ (self.state)) & self.mask
        self.state = ((self.state >> self.b) ^ (self.state)) & self.mask
        self.state = ((self.state << self.c) ^ (self.state)) & self.mask

class XORShiftBasicTest(unittest.TestCase):
    def test_basic(self):
        a, b, c = (13, 7, 17)
        seed = random.randint(0, 1 << 64)
        m = Module()

        m.submodules.dut = dut = XORShiftRandomizer(init=seed, a=a, b=b, c=c)
        ref = XORShiftRandomizerReference(seed, a, b, c)

        ref_signal = Signal(64)

        def process():
            self.assertEqual((yield dut.o), 0)
            yield ref_signal.eq(ref.state)
            yield dut.req.eq(1)

            # takes 4 cycles for the state to update after requesting it
            yield
            yield
            yield
            yield

            ref.advance()
            yield ref_signal.eq(ref.state)

            yield
            self.assertEqual((yield dut.o), ref.state)


        sim = Simulator(m)
        sim.add_sync_process(process)
        sim.add_clock(1e-6)

        with sim.write_vcd("test.vcd", traces=[ref_signal]):
            sim.run()
