from nmigen import *
from .util import PWM
from platform.icebreaker import SinglePortMemory
from ledpanel import PanelDriver

class Framebuffer(Elaboratable):
    def __init__(self):
        self.r_addr = Signal(range(64 * 32), reset_less=True)
        self.r_data = Signal(24, reset_less=True)

        self.w_addr = Signal(range(64 * 32), reset_less=True)
        self.w_data = Signal(24, reset_less=True)
        self.w_enable = Signal(3, reset_less=True)

    def elaborate(self, platform):
        import random

        m = Module()

        # RGB image planes
        random.seed(0)
        for i in range(3):

            # green plane is always on
            off_color = 0x00
            if i == 1:
                off_color = 0x7f

            mem = Memory(width=8, depth=64 * 32, init=[
                random.randint(0, 255) for _ in range(64 * 32)
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
    """
    LATENCY = 0

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

    def elaborate(self, platform):
        m = Module()

        x = self.x
        y = self.y

        # Defaults
        m.d.comb += self.framebuffer.w_enable.eq(0)

        # heartbeat tracer drop
        is_zero_zero = (x == 0) & (y == self.frame[0:6])
        val_zero_zero = 1 # self.frame[1]

        # Framebuffer readback
        rgb8 = Signal(24)

        m.submodules.pwm_r = pwm_r = PWM(rgb8[ 0: 8], self.subframe)
        m.submodules.pwm_g = pwm_g = PWM(rgb8[ 8:16], self.subframe)
        m.submodules.pwm_b = pwm_b = PWM(rgb8[16:24], self.subframe)

        m.d.comb += self.framebuffer.r_addr.eq(Cat(x, y)[0:11])
        m.d.comb += rgb8.eq(self.framebuffer.r_data)

        # sim ram -> framebuffer blitter data
        pos_counter = Signal(range(64 * 32))

        # Simulation data
        m.submodules.sim_ram = sim_ram = SinglePortMemory()
        sim_running = Signal()
        sim_location = Signal(range(64 * 64))

        with m.If(sim_running):
            # Simulation tick
            m.d.comb += sim_ram.address.eq(sim_location)
            m.d.comb += sim_ram.w_data.eq(Repl(sim_location[0:8], 2))
            m.d.sync += sim_ram.rw.eq(1)
            m.d.sync += sim_location.eq(sim_location + 1)
            with m.If(sim_location == (64 * 64 - 1)):
                m.d.sync += sim_ram.rw.eq(0)
                m.d.sync += sim_running.eq(0)
        with m.Else():
            m.d.sync += sim_ram.rw.eq(0)
            m.d.comb += sim_ram.address.eq(pos_counter)

            # framebuffer write
            with m.If(self.driver.o_unbuffered_blank.matches('1-')):
                m.d.sync += pos_counter.eq(pos_counter + 1)
                m.d.comb += self.framebuffer.w_addr.eq(pos_counter)
                m.d.comb += self.framebuffer.w_data.eq(sim_ram.r_data)
                m.d.comb += self.framebuffer.w_enable.eq(1)
            with m.If(pos_counter == 0):
                m.d.sync += sim_running.eq(1)
                m.d.sync += sim_location.eq(0)
                m.d.sync += sim_ram.rw.eq(1)

        # output colors to the scanner
        rgb = Signal(3)

        m.d.comb += rgb.eq(Mux(is_zero_zero,
                Cat(val_zero_zero, sim_running, 0),
                Cat(pwm_r.o_bit, pwm_g.o_bit, pwm_b.o_bit)
            ))
        m.d.comb += self.o_rgb.eq(rgb)

        return m

