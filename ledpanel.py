from nmigen import *

class LEDBlinker(Elaboratable):
    def __init__(self, clk_freq):
        self.o = Signal(1)
        self.clk_freq = clk_freq

    def elaborate(self, platform):
        m = Module()

        half_freq = int(self.clk_freq // 100)

        timer = Signal(range(half_freq + 1))

        flop = Signal(1)

        m.d.comb += self.o.eq(flop)

        with m.If(timer == half_freq):
            m.d.sync += flop.eq(~flop)
            m.d.sync += timer.eq(0)
        with m.Else():
            m.d.sync += timer.eq(timer + 1)

        return m

class LEDForward(Elaboratable):
    def __init__(self, clk_freq):
        self.i = Signal(3)
        self.o = Signal(3)
        self.clk_freq = clk_freq

    def elaborate(self, platform):
        m = Module()

        half_freq = int(self.clk_freq // 2)

        timer = Signal(range(half_freq + 1))

        flop = Signal(1)
        led_out = Signal(self.i.shape())

        m.d.comb += self.o.eq(flop)

        with m.If(timer == half_freq):
            m.d.sync += flop.eq(~flop)
            m.d.sync += timer.eq(0)
        with m.Else():
            m.d.sync += timer.eq(timer + 1)

        m.d.comb += self.o.eq(self.i & Repl(flop, self.i.width))

        return m
