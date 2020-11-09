from nmigen import *

class PanelDriver(Elaboratable):
    def __init__(self, painter_latency, clk_freq, bpp=8):
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

        self.painter_latency = painter_latency
        assert painter_latency <= 2

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

        init_reg = Signal(16)
        init_lcnt = Signal(7)
        delay_counter = Signal(range(self.painter_latency + 1), reset=0b00)

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
        m.d.comb += y0.eq(Cat(y, 0))
        m.d.comb += y1.eq(Cat(y, 1))

        m.d.comb += self.o_x.eq(x)
        m.d.comb += self.o_y0.eq(y0)
        m.d.comb += self.o_y1.eq(y1)
        m.d.comb += self.o_subframe.eq(subframe)
        m.d.comb += self.o_frame.eq(frame)

        state_out = Signal(3)
        if platform is not None:
            out_dbg_leds = Cat(
                platform.request('led', 3),
                platform.request('led', 4),
                platform.request('led', 5),
            )

            m.d.comb += out_dbg_leds.eq(state_out)

        with m.FSM() as fsm:
            with m.State("START"):
                m.d.sync += state_out.eq(0b001)
                m.d.sync += blank.eq(0b11)
                m.d.sync += init_reg.eq(FM6126_INIT_1)
                m.d.sync += init_lcnt.eq(52)
                m.d.sync += counter.eq(0)
                m.d.sync += self.o_rdy.eq(0)
                m.next = "INIT_R1"
            with m.State("INIT_R1"):
                m.d.sync += state_out.eq(0b011)
                m.d.sync += blank.eq(0b11)
                ireg15 = Repl(init_reg[15], 3)
                m.d.sync += led_rgb0.eq(ireg15)
                m.d.sync += led_rgb1.eq(ireg15)
                m.d.sync += init_reg.eq(init_reg.rotate_left(1))

                m.d.sync += latch.eq(Repl(init_lcnt[-1], 2))
                m.d.sync += init_lcnt.eq(init_lcnt - 1)

                m.d.sync += counter.eq(counter + 1);
                m.d.sync += sclk.eq(0b10);

                with m.If(counter[0:6] == 63):
                    m.next = "INIT_R1E"
            with m.State("INIT_R1E"):
                m.d.sync += state_out.eq(0b010)
                m.d.sync += latch.eq(0b00)
                m.d.sync += sclk.eq(0b00)
                m.d.sync += init_reg.eq(FM6126_INIT_2)
                m.d.sync += init_lcnt.eq(51)
                m.next = "INIT_R2"
            with m.State("INIT_R2"):
                m.d.sync += state_out.eq(0b100)
                m.d.sync += blank.eq(0b11)
                ireg15 = Repl(init_reg[15], 3)
                m.d.sync += led_rgb0.eq(ireg15)
                m.d.sync += led_rgb1.eq(ireg15)
                m.d.sync += init_reg.eq(init_reg.rotate_left(1))

                m.d.sync += latch.eq(Repl(init_lcnt[-1], 2))
                m.d.sync += init_lcnt.eq(init_lcnt - 1)

                m.d.sync += counter.eq(counter + 1);
                m.d.sync += sclk.eq(0b10);

                with m.If(counter[0:x.width] == self.columns - 1):
                    m.next = "INIT_R2E"
            with m.State("INIT_R2E"):
                m.d.sync += state_out.eq(0b010)
                m.d.sync += latch.eq(0b00)
                m.d.sync += sclk.eq(0b00)
                m.d.sync += counter.eq(0)
                m.d.sync += painter_counter.eq(0)
                m.d.sync += delay_counter.eq(0)
                if self.painter_latency == 0:
                    m.d.sync += self.o_rdy.eq(1)
                    m.next = "SHIFT"
                else:
                    m.d.sync += self.o_rdy.eq(1)
                    m.next = "INIT_DELAY"
            with m.State("INIT_DELAY"):
                m.d.sync += delay_counter.eq(delay_counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                with m.If(delay_counter == self.painter_latency):
                    # m.d.sync += y_reg.eq(y)
                    m.d.sync += self.o_rdy.eq(1)
                    m.next = "SHIFT"
            with m.State("SHIFT0"):
                m.d.sync += led_rgb0.eq(self.i_rgb0)
                m.d.sync += led_rgb1.eq(self.i_rgb1)
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                m.d.sync += blank.eq(0b00)
                m.d.sync += sclk.eq(0b10)
                m.next = "SHIFT"
            with m.State("SHIFT"):
                m.d.sync += state_out.eq(0b000)
                m.d.sync += led_rgb0.eq(self.i_rgb0)
                m.d.sync += led_rgb1.eq(self.i_rgb1)
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                m.d.sync += sclk.eq(0b10)
                with m.If(counter[0:x.width] == self.columns - 2):
                    m.next = "SHIFTE"
            with m.State("SHIFTE"):
                m.d.sync += led_rgb0.eq(self.i_rgb0)
                m.d.sync += led_rgb1.eq(self.i_rgb1)
                # m.d.sync += y_reg.eq(y)
                m.d.sync += blank.eq(0b01)
                m.next = "BLANK"
            with m.State("BLANK"):
                m.d.sync += led_addr_reg.eq(led_addr)
                m.d.sync += blank.eq(0b11)
                m.d.sync += latch.eq(0b11)
                m.d.sync += sclk.eq(0b00);
                m.next = "UNBLANK"
            with m.State("UNBLANK"):
                m.d.sync += counter.eq(counter + 1)
                m.d.sync += painter_counter.eq(painter_counter + 1)
                m.d.sync += blank.eq(0b10)
                m.d.sync += latch.eq(0b00)
                m.next = "SHIFT0"

        m.d.comb += self.o_rgb0.eq(led_rgb0)
        m.d.comb += self.o_rgb1.eq(led_rgb1)
        m.d.comb += self.o_blank.eq(blank)
        m.d.comb += self.o_latch.eq(latch)
        m.d.comb += self.o_sclk.eq(sclk)
        m.d.comb += self.o_addr.eq(led_addr_reg)

        return m
