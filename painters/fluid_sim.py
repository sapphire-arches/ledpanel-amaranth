from amaranth import *
from .util import PWM, XORShiftRandomizer
from platform.icebreaker import SinglePortMemory
from ledpanel import PanelDriver

class Framebuffer(Elaboratable):
    """
    Framebuffer for half of the panel (64x32 pixels).

    This is implemented as a dual-port memory, so data may be read and written
    to the framebuffer at the same time.

    Attributes
    ----------
    r_addr : Signal(11), input
        Address to read from
    r_data : Signal(24), output
        Data output from the read port. There is no latency between updating
        ``r_addr`` and ``r_data`` being valid.
    w_addr : Signal(11), input
        Address to write to
    w_data : Signal(11), input
        Data to write
    w_enable : Signal(1), input
        Write enable signal. When high, the data coming in on ``w_data`` is
        written to the address at ``w_addr``. If ``w_addr == r_addr`` then
        ``r_data == w_data`` on the current cycle.
    """
    def __init__(self):
        self.r_addr = Signal(range(64 * 32), reset_less=True)
        self.r_data = Signal(24, reset_less=True)

        self.w_addr = Signal(range(64 * 32), reset_less=True)
        self.w_data = Signal(24, reset_less=True)
        self.w_enable = Signal(1, reset_less=True)

    def elaborate(self, platform):
        import random

        m = Module()

        # RGB image planes
        random.seed(3)
        plane_names = ['r', 'g', 'b']
        for i in range(3):

            # green plane is always on

            mem = Memory(width=8, depth=64 * 32, name = 'plane_' + plane_names[i], init=[
                0xff for _ in range(64 * 32)
            ])

            read_port = mem.read_port()
            m.submodules += read_port
            m.d.comb += read_port.addr.eq(self.r_addr)
            m.d.comb += self.r_data[(i * 8):(i + 1) * 8].eq(read_port.data)

            write_port = mem.write_port()
            m.submodules += write_port
            m.d.comb += write_port.addr.eq(self.w_addr)
            m.d.comb += write_port.data.eq(self.w_data[(i * 8):(i + 1) * 8])
            m.d.comb += write_port.en.eq(self.w_enable)

        return m

class Painter(Elaboratable):
    """
    Painter for the fluid simulator.

    Attributes
    ----------
    o_rgb : Signal(3), output
        Single-bit output for each of the R,G,B channels

    fb_w_addr: Signal(11), input
        See documentation of :class:`Framebuffer`
    fb_w_data: Signal(24), input
        See documentation of :class:`Framebuffer`
    fb_w_enable: Signal(1), input
        See documentation of :class:`Framebuffer`
    """
    LATENCY = 1

    def __init__(self, driver: PanelDriver, side: int, framebuffer: Framebuffer):
        self.driver = driver
        self.x = driver.o_x
        self.frame = driver.o_frame
        self.subframe = driver.o_subframe
        self.framebuffer = framebuffer
        self.side = side
        if side == 0:
            self.y = driver.o_y0
            self.o_rgb = driver.i_rgb0
        elif side == 1:
            self.y = driver.o_y1
            self.o_rgb = driver.i_rgb1
        else:
            raise ValueError("Driver doesn't export side {}".format(side))

        self.fb_w_addr = Signal(11)
        self.fb_w_data = Signal(24)
        self.fb_w_enable = Signal(1)

    def elaborate(self, platform):
        m = Module()

        x = self.x
        y = self.y

        # heartbeat tracer drop
        is_zero_zero = (y == 0) & (x == self.frame[0:6])
        val_zero_zero = 1 # self.frame[1]
        is_zero_zero_ff = Signal()
        m.d.sync += is_zero_zero_ff.eq(is_zero_zero)

        # Framebuffer readback
        rgb8 = Signal(24)

        m.submodules.pwm_r = pwm_r = PWM(rgb8[ 0: 8], self.subframe)
        m.submodules.pwm_g = pwm_g = PWM(rgb8[ 8:16], self.subframe)
        m.submodules.pwm_b = pwm_b = PWM(rgb8[16:24], self.subframe)

        m.d.comb += rgb8.eq(self.framebuffer.r_data)
        m.d.comb += self.framebuffer.r_addr.eq(Cat(x, y))

        # Framebuffer write binding
        m.d.comb += [
            self.framebuffer.w_addr.eq(self.fb_w_addr),
            self.framebuffer.w_data.eq(self.fb_w_data),
            self.framebuffer.w_enable.eq(self.fb_w_enable),
        ]

        # output colors to the scanner
        rgb = Signal(3)

        m.d.comb += rgb.eq(Mux(is_zero_zero_ff,
                Cat(0, 0, val_zero_zero),
                Cat(pwm_r.o_bit, pwm_g.o_bit, pwm_b.o_bit)
            ))
        m.d.comb += self.o_rgb.eq(rgb)

        return m


class SimDoubleBuffer(Elaboratable):
    """
    Double buffer the simulation memory, effectively turning two single port
    memories into a dual port memory where we write to one while reading from
    the other (with independent address control).

    Attributes
    ----------
    frame : Signal(1), input
        Which frame us currently being read. The other frame is currently being
        written.

    r_address : Signal(range(64 * 64)), input
        The read address
    r_data : Signal(16), output
        Data from the read address, has one cycle of latency from ``r_address``

    w_address : Signal(range(64 * 64)), output
        The write address
    w_data : Signal(16), input
        Data to write
    w_enable : Signal(), input
        Enables writes
    """

    def __init__(self):
        self.r_address = Signal(range(64 * 64))
        self.r_data = Signal(16)

        self.w_address = Signal(range(64 * 64))
        self.w_data = Signal(16)
        self.w_enable = Signal()

        self.frame = Signal()

    def elaborate(self, platform):
        m = Module()

        rams = [SinglePortMemory(), SinglePortMemory()]

        m.submodules += rams

        for i in range(len(rams)):
            m.d.comb += rams[i].rw.eq(0)

        with m.Switch(self.frame):
            for c_index in range(len(rams)):
                c_ram = rams[c_index]

                n_index = (c_index + 1) % len(rams)
                n_ram = rams[n_index]
                with m.Case(c_index):
                    m.d.comb += [
                        c_ram.address.eq(self.r_address),
                        self.r_data.eq(c_ram.r_data),

                        n_ram.address.eq(self.w_address),
                        n_ram.w_data.eq(self.w_data),
                        n_ram.rw.eq(self.w_enable),
                    ]

        return m


class FluidSim(Elaboratable):
    """
    Performs fluid simulation in a buffer.

    Attributes
    ----------
    start : Signal(1), input
        Signal which indicates the start of a new frame when pulled high
        externally.
    """
    def __init__(self, painter0: Painter, painter1: Painter):
        self.painter0 = painter0
        self.painter1 = painter1
        self.start = Signal()
        self.buffers = SimDoubleBuffer()

    def elaborate(self, platform):
        m = Module()

        m.submodules.buffers = self.buffers

        m.submodules.randomizer = randomizer = XORShiftRandomizer()
        m.d.comb += randomizer.req.eq(1)

        # Local signals
        sim_counter = Signal(range(64 * 64 + 1))
        current_frame = Signal()

        m.d.comb += self.buffers.frame.eq(current_frame)

        with m.FSM():
            with m.State("SIM_INIT_START"):
                m.d.sync += sim_counter.eq(0)
                m.d.sync += current_frame.eq(0)
                m.next = "SIM_INIT"
            with m.State("SIM_INIT"):
                m.d.comb += self.buffers.w_address.eq(sim_counter)

                randomizer_bit_counter = Signal(range(3))

                with m.Switch(randomizer_bit_counter):
                    for i in range(3):
                        with m.Case(i):
                            with m.If(randomizer.o[i*2:(i+1)*2] == 0):
                                m.d.comb += self.buffers.w_data.eq(0xffff)
                            with m.Else():
                                m.d.comb += self.buffers.w_data.eq(0x0000)

                            if i == 2:
                                m.d.sync += randomizer_bit_counter.eq(0)
                            else:
                                m.d.sync += randomizer_bit_counter.eq(i + 1)

                m.d.comb += self.buffers.w_enable.eq(1)
                m.d.sync += sim_counter.eq(sim_counter + 1)
                with m.If(sim_counter == (64 * 64)):
                    m.next = "SIM_RUN_START"
            with m.State("SIM_RUN_START"):
                m.d.sync += sim_counter.eq(0)
                m.d.comb += self.buffers.w_enable.eq(0)
                m.next = "SIM_RUN_0"
            with m.State("SIM_RUN_0"):
                m.next = "SIM_DONE"
            with m.State("SIM_DONE"):
                m.d.sync += sim_counter.eq(0)
                m.d.sync += current_frame.eq(1)
                m.next = "WRITE_PAINTER0"
            with m.State("WRITE_PAINTER0"):
                self.painter_write_phase(m, sim_counter, self.painter0, 64 * 32, "WRITE_PAINTER1")
                with m.If(sim_counter == 64 * 32):
                    m.d.sync += self.painter1.fb_w_enable.eq(1)
            with m.State("WRITE_PAINTER1"):
                self.painter_write_phase(m, sim_counter, self.painter1, 64 * 64, "WAIT_FOR_NEXT")
            with m.State("WAIT_FOR_NEXT"):
                with m.If(self.start):
                    m.next = "SIM_RUN_START"

        return m

    def painter_write_phase(self, m: Module, sim_counter: Signal, painter: Painter, end_count: int, next_state: str):
        m.d.sync += sim_counter.eq(sim_counter + 1)
        m.d.sync += painter.fb_w_enable.eq(1)

        # the framebuffer address must lag the simulation data address by 1
        # cycle, because the single port RAM registers its input
        m.d.comb += self.buffers.r_address.eq(sim_counter)
        m.d.comb += painter.fb_w_addr.eq(sim_counter[0:11])
        m.d.comb += painter.fb_w_data.eq(Cat(
            self.buffers.r_data[0:8],
            self.buffers.r_data[8:16],
            Const(0, shape=8),
        ))

        with m.If(sim_counter == end_count):
            m.next = next_state
            m.d.sync += painter.fb_w_enable.eq(0)
