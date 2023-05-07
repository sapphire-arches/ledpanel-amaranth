from amaranth import *

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
        # m.d.comb += self.o_bit.eq(self.v[0])

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

class XORShiftRandomizer(Elaboratable):
    """
    An xor-shift based randomizer.

    Based on "Xorshift RNGs" by George Marsaglia, DOI 10.18637/jss.v008.i14


    Attributes
    ----------
    o: Signal(64), output
        Output value of the randomizer, changes every 3 cycles from the last
        positive edge on the ``req`` line
    req: Signal(), input
        Should be pulled high when the randomizer should run
    """

    def __init__(self, init=None, a=13, b=7, c=17):
        self.o = Signal(64)
        self.req = Signal()

        if init is None:
            import random
            self.init = random.randint(0, 1 << 64)
        else:
            self.init = init
        self.a = a
        self.b = b
        self.c = c

    def elaborate(self, platform):
        m = Module()

        rstate = Signal(64, reset=self.init);
        ostate = Signal(64);

        with m.FSM():
            with m.State("WAIT_REQ"):
                with m.If(self.req):
                    m.next = "PH0"
            with m.State("PH0"):
                m.d.sync += rstate.eq((rstate << self.a) ^ rstate)
                m.next = "PH1"
            with m.State("PH1"):
                m.d.sync += rstate.eq((rstate >> self.b) ^ rstate)
                m.next = "PH2"
            with m.State("PH2"):
                next_state = (rstate << self.c) ^ rstate
                m.d.sync += rstate.eq(next_state)
                m.d.sync += ostate.eq(next_state)

                with m.If(self.req):
                    m.next = "PH0"
                with m.Else():
                    m.next = "WAIT_REQ"

        m.d.comb += self.o.eq(ostate)


        return m
