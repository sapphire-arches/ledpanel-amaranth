from nmigen import *
from nmigen.asserts import *
from enum import Enum

def PanelSignal(rgb0, rgb1, addr, blank, latch, sclk):
    assert rgb0.shape().width == 3
    assert rgb1.shape().width == 3
    assert addr.shape().width == 5
    assert blank.shape().width == 2
    assert latch.shape().width == 2
    assert sclk.shape().width == 2

    return Cat(rgb0, rgb1, addr, blank, latch, sclk)

class PanelMux(Elaboratable):
    PANEL_WIDTH = 3 + 3 + 5 + 2 + 2 + 2

    def __init__(self, sel, i0, i1):
        sel = Value.cast(sel)
        assert sel.shape().width == 1
        assert i0.shape().width == PanelMux.PANEL_WIDTH
        assert i1.shape().width == PanelMux.PANEL_WIDTH

        self.sel = sel
        self.i0 = i0
        self.i1 = i1
        self.o = Signal(PanelMux.PANEL_WIDTH)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.o.eq(Mux(self.sel, self.i1, self.i0))


        return m

class FM6126StartupDriver(Elaboratable):
    """ Scans out the startup sequence required to program FM6126 shift registers
    """
    def __init__(self, o_panel):
        self.panel = o_panel
        self.done = Signal()

    def elaborate(self, platform):
        m = Module()

        # we only need 1 RGB register since we scan out identical data to both
        # banks of FM6126s
        o_rgb = Signal(3)
        o_blank = Signal(2, reset=0b11)
        o_latch = Signal(2)
        o_sclk = Signal(2)

        m.d.comb += self.panel.eq(PanelSignal(
            o_rgb,
            o_rgb,
            Const(0, 5), # No need to talk to the row drivers
            o_blank,
            o_latch,
            o_sclk,
        ))

        # The FM6126 chip needs to see a magic sequence on all of the channels
        # before it will start
        FM6126_INIT_1 = 0x7FFF
        FM6126_INIT_2 = 0x0040

        init_reg = Signal(16)
        latch_counter = Signal(range(64 + 1))
        counter = Signal(range(64 + 1))

        done = Signal()
        m.d.comb += self.done.eq(done)

        class State(Enum):
            START     = 0x0
            INIT_R1   = 0x1
            INIT_R1_E = 0x2
            INIT_R2   = 0x3
            INIT_R2_E = 0x4
            DONE      = 0x5

        with m.FSM() as fsm:
            with m.State(State.START):
                m.d.sync += o_blank.eq(0b11)
                m.d.sync += o_latch.eq(0b00)
                m.d.sync += init_reg.eq(FM6126_INIT_1)
                m.d.sync += latch_counter.eq(52)
                m.d.sync += counter.eq(0)
                m.d.sync += done.eq(0)
                m.next = State.INIT_R1
            with m.State(State.INIT_R1):
                ireg15 = Repl(init_reg[15], 3)
                m.d.sync += o_rgb.eq(ireg15)
                m.d.sync += init_reg.eq(init_reg.rotate_left(1))
                m.d.sync += o_latch.eq(Repl(latch_counter[-1], 2))
                m.d.sync += latch_counter.eq(latch_counter - 1)
                m.d.sync += o_sclk.eq(0b10)
                m.d.sync += counter.eq(counter + 1)

                with m.If(counter == 63):
                    m.next = State.INIT_R1_E
            with m.State(State.INIT_R1_E):
                m.d.sync += o_latch.eq(0b00)
                m.d.sync += o_sclk.eq(0b00)
                m.d.sync += init_reg.eq(FM6126_INIT_2)
                m.d.sync += latch_counter.eq(51)
                m.d.sync += counter.eq(0)
                m.next = State.INIT_R2
            with m.State(State.INIT_R2):
                ireg15 = Repl(init_reg[15], 3)
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += init_reg.eq(init_reg.rotate_left(1))
                m.d.sync += latch_counter.eq(latch_counter - 1)
                m.d.sync += o_latch.eq(Repl(latch_counter[-1], 2))
                m.d.sync += o_rgb.eq(ireg15)
                m.d.sync += o_sclk.eq(0b10)

                with m.If(counter == 63):
                    m.next = State.INIT_R2_E
            with m.State(State.INIT_R2_E):
                m.d.sync += o_latch.eq(0b00)
                m.d.sync += o_sclk.eq(0b00)
                m.next = State.DONE
            with m.State(State.DONE):
                m.d.sync += done.eq(1)
                m.next = State.DONE

        return m

class PixelScanner(Elaboratable):
    def __init__(self, painter_latency, bpp):
        self.columns = 64       # TODO: make generic
        self.bpp = bpp

        self.o_rgb0 = Signal(3)
        self.o_rgb1 = Signal(3)
        self.o_addr = Signal(5)
        self.o_blank = Signal(2)
        self.o_latch = Signal(2)
        self.o_sclk = Signal(2)
        self.o_rdy = Signal(1, reset=0)

        self.o_x  = Signal(range(self.columns))
        self.o_y0 = Signal(self.o_addr.width + 1)
        self.o_y1 = Signal(self.o_addr.width + 1)
        self.o_frame = Signal(12)
        self.o_subframe = Signal(self.bpp)

        self.i_rgb0 = Signal(3)
        self.i_rgb1 = Signal(3)
        self.i_start = Signal(1)

        self.painter_latency = painter_latency
        assert painter_latency <= 2
        assert self.bpp == 8

    def startup_cycles(self):
        # START + R1 scanout + R2 scanout + painter spoolup
        return 2 + 64 + 64 + self.painter_latency


    def elaborate(self, platform):
        m = Module()

        # The FM6126 chip needs to see a magic sequence on all of the channels
        # before it will start
        FM6126_INIT_1 = 0x7FFF
        FM6126_INIT_2 = 0x0040

        # Local registers for output wires
        led_rgb0 = Signal(3)
        led_rgb1 = Signal(3)
        blank = Signal(2, reset=0b11)
        sclk = Signal(2, reset=0b00)
        latch = Signal(2, reset=0b00)

        startup_delay = self.painter_latency
        delay_counter = Signal(range(startup_delay + 1), reset=0)

        # Data required by painters. The painter_counter should always lead the main counter by
        x = Signal(range(self.columns))
        y = Signal(5)
        subframe = Signal(self.bpp)
        frame = Signal(self.o_frame.width)
        counter_comb = Cat(x, y, subframe, frame)
        painter_counter = Signal(counter_comb.shape().width)
        m.d.comb += counter_comb.eq(painter_counter)

        # Values for tracking what we're sending to the panel
        counter = Signal(counter_comb.shape().width)
        led_addr = Signal(5)
        led_addr_reg = Signal(5)

        m.d.comb += led_addr.eq(counter[x.width:(x.width + led_addr_reg.width)])

        y_reg = Signal(led_addr.width)
        y0 = Signal(6)
        y1 = Signal(6)
        m.d.comb += y0.eq(Cat(y_reg, 0))
        m.d.comb += y1.eq(Cat(y_reg, 1))

        m.d.comb += self.o_x.eq(x)
        m.d.comb += self.o_y0.eq(y0)
        m.d.comb += self.o_y1.eq(y1)
        m.d.comb += self.o_subframe.eq(subframe)
        m.d.comb += self.o_frame.eq(frame)

        class FSMState(Enum):
            WAIT_START = 0x0
            START      = 0x1
            INIT_DELAY = 0x2
            SHIFT0     = 0x3
            SHIFT      = 0x4
            SHIFTE     = 0x5
            BLANK      = 0x6
            UNBLANK    = 0x7

        with m.FSM() as pixel_fsm:
            with m.State(FSMState.WAIT_START):
                m.d.sync += blank.eq(0b11)
                m.d.sync += latch.eq(0b00)
                m.d.sync += sclk.eq(0b00)
                m.d.sync += counter.eq(0)
                m.d.sync += delay_counter.eq(0)
                m.d.sync += painter_counter.eq(0)
                m.d.sync += self.o_rdy.eq(0)
                with m.If(self.i_start):
                    m.next = FSMState.START
                with m.Else():
                    m.next = FSMState.WAIT_START
            with m.State(FSMState.START):
                m.d.sync += blank.eq(0b11)
                m.d.sync += counter.eq(0)
                m.d.sync += delay_counter.eq(0)
                m.d.sync += latch.eq(0b00)
                # Painter counter starts at 1 because we have 1 cycle of
                # internal latency to the outputs (due to the DFF for the
                # address lines)
                m.d.sync += painter_counter.eq(0)
                m.d.sync += y_reg.eq(0)
                m.d.sync += sclk.eq(0b00)
                m.d.sync += self.o_rdy.eq(0)
                m.next = FSMState.SHIFT
            with m.State(FSMState.INIT_DELAY):
                m.d.sync += delay_counter.eq(delay_counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                with m.If(delay_counter == startup_delay):
                    if platform == "formal":
                        m.d.sync += Assert(counter == Past(painter_counter, self.painter_latency + 2))
                    # m.d.sync += y_reg.eq(y)
                    m.d.sync += self.o_rdy.eq(1)
                    m.next = FSMState.SHIFT
            with m.State(FSMState.SHIFT0):
                m.d.sync += led_rgb0.eq(self.i_rgb0)
                m.d.sync += led_rgb1.eq(self.i_rgb1)
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                m.d.sync += blank.eq(0b00)
                m.d.sync += sclk.eq(0b10)
                m.next = FSMState.SHIFT
            with m.State(FSMState.SHIFT):
                m.d.sync += led_rgb0.eq(self.i_rgb0)
                m.d.sync += led_rgb1.eq(self.i_rgb1)
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                m.d.sync += sclk.eq(0b10)
                m.d.sync += blank.eq(0b00)
                with m.If(counter[0:x.width] == self.columns - 2):
                    m.next = FSMState.SHIFTE
            with m.State(FSMState.SHIFTE):
                m.d.sync += led_rgb0.eq(self.i_rgb0)
                m.d.sync += led_rgb1.eq(self.i_rgb1)
                m.d.sync += y_reg.eq((y + 1)[0:5])
                m.d.sync += blank.eq(0b01)
                m.next = FSMState.BLANK
            with m.State(FSMState.BLANK):
                m.d.sync += led_addr_reg.eq(led_addr)
                m.d.sync += blank.eq(0b11)
                m.d.sync += latch.eq(0b11)
                m.d.sync += sclk.eq(0b00);
                m.next = FSMState.UNBLANK
            with m.State(FSMState.UNBLANK):
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                m.d.sync += blank.eq(0b10)
                m.d.sync += latch.eq(0b00)
                m.next = FSMState.SHIFT0

        # Some formal properties that we just assume
        if platform == "formal":
            with m.If(self.o_sclk.any()):
                m.d.sync += Assert(counter[0:x.width] == Past(self.o_x, self.painter_latency + 2))
            with m.If(pixel_fsm.ongoing(FSMState.SHIFT0)):
                m.d.sync += Assume(counter[0:x.width] == 0)

        m.d.comb += self.o_rgb0.eq(led_rgb0)
        m.d.comb += self.o_rgb1.eq(led_rgb1)
        m.d.comb += self.o_blank.eq(blank)
        m.d.comb += self.o_latch.eq(latch)
        m.d.comb += self.o_sclk.eq(sclk)
        m.d.comb += self.o_addr.eq(led_addr_reg)

        return m

class PanelDriver(Elaboratable):
    def __init__(self, painter_latency, bpp=8):
        self.painter_latency = painter_latency
        self.columns = 64       # TODO: make generic
        self.bpp = 8

        self.o_rgb0 = Signal(3)
        self.o_rgb1 = Signal(3)
        self.o_addr = Signal(5)
        self.o_blank = Signal(2)
        self.o_latch = Signal(2)
        self.o_sclk = Signal(2)
        self.o_rdy = Signal(1)

        self.o_x  = Signal(range(self.columns))
        self.o_y0 = Signal(self.o_addr.width + 1)
        self.o_y1 = Signal(self.o_addr.width + 1)
        self.o_frame = Signal(12)
        self.o_subframe = Signal(self.bpp)

        self.i_rgb0 = Signal(3)
        self.i_rgb1 = Signal(3)

    def elaborate(self, platform):
        m = Module()

        o_pix = Signal(PanelMux.PANEL_WIDTH)
        o_startup = Signal(PanelMux.PANEL_WIDTH)
        o_panel = PanelSignal(self.o_rgb0, self.o_rgb1, self.o_addr, self.o_blank,
                              self.o_latch, self.o_sclk)

        m.submodules.pix = pix = PixelScanner(self.painter_latency, self.bpp)
        m.submodules.startup = startup = FM6126StartupDriver(o_startup)
        m.submodules.mux = mux = PanelMux(startup.done, o_startup, o_pix)

        m.d.comb += pix.i_start.eq(startup.done)
        m.d.comb += o_panel.eq(mux.o)

        m.d.comb += o_pix.eq(PanelSignal(
            pix.o_rgb0,
            pix.o_rgb1,
            pix.o_addr,
            pix.o_blank,
            pix.o_latch,
            pix.o_sclk,
        ))
        m.d.comb += self.o_rdy.eq(pix.o_rdy)
        m.d.comb += self.o_x.eq(pix.o_x)
        m.d.comb += self.o_y0.eq(pix.o_y0)
        m.d.comb += self.o_y1.eq(pix.o_y1)
        m.d.comb += self.o_frame.eq(pix.o_frame)
        m.d.comb += self.o_subframe.eq(pix.o_subframe)
        m.d.comb += pix.i_rgb0.eq(self.i_rgb0)
        m.d.comb += pix.i_rgb1.eq(self.i_rgb1)

        return m
