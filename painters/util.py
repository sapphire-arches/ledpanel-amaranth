from nmigen import *

class PWM(Elaboratable):
    """
    PWM module which converts a multi-bit channel value into a single-bit
    output for the current subframe.

    This bit-reverses the subframe signal to hopefully increase the minimum
    flicker frequency of the driven signal.

    Attributes
    ----------
    v: Signal(n), input
        Signal carrying the input value.
    subframe: Signal(n), input
        Signal carrying the current subframe.
    o_bit: Signal(1), output
        Bit representing the 
    """
    def __init__(self, v: Signal, subframe: Signal):
        self.v = v
        self.subframe = subframe
        assert v.shape().width == subframe.shape().width
        self.o_bit = Signal()

    def elaborate(self, platform):
        m = Module()

        # Reverse the subframe so the minimum flicker frequency is higher
        rev = Signal(self.v.shape())
        m.d.comb += [rev[rev.width - i - 1].eq(self.subframe[i]) for i in range(rev.width)]

        m.d.comb += self.o_bit.eq(self.v > rev)

        return m

class LFSR(Elaboratable):
    def __init__(self, taps, width=32):
        self.taps = taps
        self.o = Signal(width)
        self.i_advance = Signal(1)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i_advance):
            feedback = Cat(
                self.o[1:],
                ~(self.o & self.taps).xor(),
            )
            m.d.sync += self.o.eq(feedback)

        return m

