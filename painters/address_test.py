from amaranth import *

class CycleAddrTest(Elaboratable):
    MAX_TEST_CYCLES = 2

    def __init__(self, cycles, driver, side):
        self.x = driver.o_x
        self.frame = driver.o_frame
        self.subframe = driver.o_subframe
        if side == 0:
            self.y = driver.o_y0
            self.o_rgb = driver.i_rgb0
        elif side == 1:
            self.y = driver.o_y1
            self.o_rgb = driver.i_rgb1
        else:
            raise ValueError("Driver doesn't export side {}".format(side))

        assert cycles < 3
        self.cycles = cycles

    def elaborate(self, platform):
        m = Module()

        x = self.x
        y = self.y

        border_y = (y == 0) | (y == 63) # y == self.frame[0:6]
        border_x = (x == 0) | (x == 63) # x == self.frame[0:6]
        border = border_x | border_y
        x_0 = x.any() & ~((x & (x - 1)).any())
        y_0 = y.any() & ~((y & (y - 1)).any())

        subf_h = 0b0001 == self.subframe[-4:]

        rgb = Signal(3)
        rgb_ff_0 = Signal(3)
        rgb_ff_1 = Signal(3)
        m.d.comb += rgb.eq(Cat(x_0 & subf_h, y_0 & subf_h, border))

        m.d.sync += rgb_ff_0.eq(rgb)
        m.d.sync += rgb_ff_1.eq(rgb_ff_0)

        if self.cycles == 0:
            m.d.comb += self.o_rgb.eq(rgb)
        elif self.cycles == 1:
            m.d.comb += self.o_rgb.eq(rgb_ff_0)
        elif self.cycles == 2:
            m.d.comb += self.o_rgb.eq(rgb_ff_1)

        return m

