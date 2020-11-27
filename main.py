from ledpanel import PanelDriver
from nmigen import *
from nmigen.build import *
from nmigen.vendor.lattice_ice40 import *
from nmigen_boards.resources import *
import argparse
import os
import subprocess

# range 0-2, 3 means use the fancy painter
TEST_CYCLES = 3

def LEDPanelPModResource(*args, conn0, conn1):
    io = []
    io.append(Subsignal("rgb0", Pins("1 2 3", dir="o", conn=conn0, assert_width=3)))
    io.append(Subsignal("rgb1", Pins("7 8 9", dir="o", conn=conn0, assert_width=3)))
    io.append(Subsignal("addr", Pins("1 2 3 4 10", dir="o", conn=conn1, assert_width=5)))
    io.append(Subsignal("blank", Pins("7", dir="o", conn=conn1, assert_width=1)))
    io.append(Subsignal("latch", Pins("8", dir="o", conn=conn1, assert_width=1)))
    io.append(Subsignal("sclk", Pins("9", dir="o", conn=conn1, assert_width=1)))

    return Resource.family(*args, default_name="led_panel", ios=io)

class ICEBreakerPlatformCustom(LatticeICE40Platform):
    device      = "iCE40UP5K"
    package     = "SG48"
    # default_clk = "clk12"
    default_clk = "SB_HFOSC"
    hfosc_div = 3

    resources   = [
        Resource("clk12", 0, Pins("35", dir="i"),
                 Clock(12e6), Attrs(GLOBAL=False, IO_STANDARD="SB_LVCMOS")),

        *LEDResources(pins="11 37", invert=True, attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        # Semantic aliases
        Resource("led_r", 0, PinsN("11", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 0, PinsN("37", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS")),

        RGBLEDResource(0, r="39", g="40", b="41", attrs=Attrs(IO_STANDARD="SB_LVCMOS")),

        *ButtonResources(pins="10", invert=True, attrs=Attrs(IO_STANDARD="SB_LVCMOS")),

        UARTResource(0,
            rx="6", tx="9",
            attrs=Attrs(IO_STANDARD="SB_LVTTL", PULLUP=1)
        ),

        *SPIFlashResources(0,
            cs="16", clk="15", copi="14", cipo="17", wp="12", hold="13",
            attrs=Attrs(IO_STANDARD="SB_LVCMOS")
        ),
    ]
    connectors = [
        Connector("pmod", 0, " 4  2 47 45 - -  3 48 46 44 - -"), # PMOD1A
        Connector("pmod", 1, "43 38 34 31 - - 42 36 32 28 - -"), # PMOD1B
        Connector("pmod", 2, "27 25 21 19 - - 26 23 20 18 - -"), # PMOD2
    ]
    # The attached LED/button section can be either used standalone or as a PMOD.
    # Attach to platform using:
    # p.add_resources(p.break_off_pmod)
    # pmod_btn = plat.request("user_btn")
    break_off_pmod = [
        *LEDResources(pins={2: "7", 3: "1", 4: "2", 5: "8", 6: "3"}, conn=("pmod", 2),
                      attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
        # Semantic aliases
        Resource("led_r", 1, Pins("7", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 1, Pins("1", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 2, Pins("2", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 3, Pins("8", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),
        Resource("led_g", 4, Pins("3", dir="o", conn=("pmod", 2)),
                 Attrs(IO_STANDARD="SB_LVCMOS")),

        *ButtonResources(pins={1: "9", 2: "4", 3: "10"}, conn=("pmod", 2),
                         attrs=Attrs(IO_STANDARD="SB_LVCMOS")),
    ]

    # resource collection for the LED panel PMOD
    led_panel_pmod = [
        LEDPanelPModResource(0, conn0=("pmod", 0), conn1=("pmod", 1))
    ]

    def toolchain_program(self, products, name):
        iceprog = os.environ.get("ICEPROG", "iceprog")
        with products.extract("{}.bin".format(name)) as bitstream_filename:
            subprocess.check_call([iceprog, bitstream_filename])


class ResetLogic(Elaboratable):
    def __init__(self, button, led):
        self.button = button
        self.led = led
        self.button_rst_out = Signal()

    def elaborate(self, platform):
        m = Module()

        button_high_cycles = int(platform.default_clk_frequency * 0.05)
        button_high_cnt = Signal(range(button_high_cycles + 1))
        was_low = Signal()

        heartbeat = Signal()
        heartbeat_counter = Signal(range(int(platform.default_clk_frequency / 2 + 1)))

        m.d.sync += heartbeat_counter.eq(heartbeat_counter + 1)
        m.d.comb += heartbeat.eq(heartbeat_counter[-1])
        m.d.comb += platform.request('led', 2).eq(heartbeat)

        with m.If(self.button):
            with m.If(button_high_cnt == button_high_cycles):
                m.d.sync += self.button_rst_out.eq(1)
                m.d.sync += button_high_cnt.eq(0)
                m.d.sync += was_low.eq(0)
            with m.Else():
                with m.If(was_low):
                    m.d.sync += button_high_cnt.eq(button_high_cnt + 1)
        with m.Else():
            m.d.sync += button_high_cnt.eq(0)
            m.d.sync += was_low.eq(1)
            with m.If(button_high_cnt == 0):
                m.d.sync += self.button_rst_out.eq(0)
            with m.Else():
                m.d.sync += button_high_cnt.eq(button_high_cnt + 1)

        m.d.comb += self.led.eq(self.button_rst_out)

        return m

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

class PWM(Elaboratable):
    def __init__(self, v, subframe):
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
        for i in range(3):
            random.seed(0)

            # green plane is always on
            off_color = 0x00
            if i == 1:
                off_color = 0x7f

            mem = Memory(width=8, depth=64 * 32, init=[
                0x7f if (i % 2) == 0 else 0 for i in range(64 * 32)
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
    LATENCY = 0

    def __init__(self, driver, side, framebuffer):
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

        is_zero_zero = (x == 0) & (y == self.frame[0:6])
        val_zero_zero = self.frame[1]

        rgb8 = Signal(24)

        m.submodules.pwm_r = pwm_r = PWM(rgb8[ 0: 8], self.subframe)
        m.submodules.pwm_g = pwm_g = PWM(rgb8[ 8:16], self.subframe)
        m.submodules.pwm_b = pwm_b = PWM(rgb8[16:24], self.subframe)

        m.d.comb += self.framebuffer.r_addr.eq(Cat(x, y)[0:11])
        m.d.comb += self.framebuffer.w_addr.eq(Cat((x + 1)[0:6], y)[0:11])
        m.d.comb += self.framebuffer.w_data.eq(rgb8)
        m.d.comb += self.framebuffer.w_enable.eq(1)
        m.d.comb += rgb8.eq(self.framebuffer.r_data)

        rgb = Signal(3)

        m.d.comb += rgb.eq(Cat(Mux(is_zero_zero, val_zero_zero, pwm_r.o_bit), pwm_g.o_bit, pwm_b.o_bit))
        m.d.comb += self.o_rgb.eq(rgb)

        return m

class BoardMapping(Elaboratable):
    def __init__(self):
        pass

    def elaborate(self, platform):
        m = Module()

        panel = platform.request('led_panel', 0, xdr={
            'sclk': 2,
            'latch': 2,
            'blank': 2,
        })

        led_v = platform.request('led', 0)
        led_r = platform.request('rgb_led', 0).r
        led = Signal()

        m.d.comb += led_v.eq(led)
        m.d.comb += led_r.eq(led)

        if TEST_CYCLES <= CycleAddrTest.MAX_TEST_CYCLES:
            driver = PanelDriver(TEST_CYCLES)
        else:
            driver = PanelDriver(Painter.LATENCY)

        cd_hsclock = ClockDomain()
        m.domains += cd_hsclock

        hsclock_lock_o = Signal()
        hsclock_lock = Signal()

        # Configure a PLL40 module for 30MHz operation
        m.submodules += Instance("SB_PLL40_PAD",
                    p_FEEDBACK_PATH="SIMPLE",
                    p_DIVR=0b0000,
                    p_DIVF=0b1001111,
                    p_DIVQ=0b101,
                    p_FILTER_RANGE=0b001,
                    i_PACKAGEPIN=platform.request("clk12"),
                    o_PLLOUTCORE=cd_hsclock.clk,
                    o_LOCK=hsclock_lock_o,
                    i_RESETB=1,
                    i_BYPASS=0
                )
        platform.add_clock_constraint(cd_hsclock.clk, 30e6)
        m.d.sync += hsclock_lock.eq(hsclock_lock_o)
        # m.d.comb += hsclock_lock.eq(1)
        # m.d.comb += cd_hsclock.clk.eq(ClockSignal("sync"))

        # Add a register for the RGB outputs and addrs to synchronize with the DDR outputs
        delay_sigs = Cat(driver.o_rgb0, driver.o_rgb1, driver.o_addr)
        delayed_sigs = Cat(panel.rgb0, panel.rgb1, panel.addr)
        delay_sigs_ff = Signal.like(delay_sigs)
        m.d.hsclock += delay_sigs_ff.eq(delay_sigs)

        # Bind I/Os
        m.d.comb += [
            delayed_sigs.eq(delay_sigs_ff),
            # panel.addr.eq(driver.o_addr),
            Cat(panel.blank.o0, panel.blank.o1).eq(driver.o_blank),
            Cat(panel.latch.o0, panel.latch.o1).eq(driver.o_latch),
            Cat(panel.sclk.o0, panel.sclk.o1).eq(driver.o_sclk),

            panel.blank.o_clk.eq(cd_hsclock.clk),
            panel.latch.o_clk.eq(cd_hsclock.clk),
            panel.sclk.o_clk.eq(cd_hsclock.clk),
        ]

        # Tie a button to the reset line
        button = platform.request('button', 0)
        reset_mod = ResetLogic(button, led)

        # Bind reset logic
        m.d.comb += cd_hsclock.rst.eq(reset_mod.button_rst_out | ResetSignal("sync") | ~hsclock_lock)

        m.d.comb += platform.request('led', 6).eq(cd_hsclock.rst)

        # Add the subdomain
        dr = DomainRenamer("hsclock")
        m.submodules.driver = dr(driver)
        m.submodules.reset_mod = reset_mod

        # Add painters
        if TEST_CYCLES < 3:
            m.submodules.painter0 = dr(CycleAddrTest(TEST_CYCLES, driver, side=0))
            m.submodules.painter1 = dr(CycleAddrTest(TEST_CYCLES, driver, side=1))
        else:
            m.submodules.framebuffer0 = framebuffer0 = dr(Framebuffer())
            m.submodules.framebuffer1 = framebuffer1 = dr(Framebuffer())
            m.submodules.painter0 = dr(Painter(driver, side=0, framebuffer=framebuffer0))
            m.submodules.painter1 = dr(Painter(driver, side=1, framebuffer=framebuffer1))

        return m

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    p_action = parser.add_subparsers(dest="action")
    p_action.add_parser("simulate")
    p_action.add_parser("program")

    args = parser.parse_args()
    if args.action == "simulate":
        from nmigen.back import cxxrtl
        clk_freq = 1e6

        m = Module()

        if TEST_CYCLES <= CycleAddrTest.MAX_TEST_CYCLES:
            driver = PanelDriver(TEST_CYCLES)
            painter0 = CycleAddrTest(TEST_CYCLES, driver, side=0)
            painter1 = CycleAddrTest(TEST_CYCLES, driver, side=1)
        else:
            driver = PanelDriver(Painter.LATENCY)
            m.submodules.framebuffer0 = framebuffer0 = Framebuffer()
            m.submodules.framebuffer1 = framebuffer1 = Framebuffer()
            painter0 = Painter(driver, side=0, framebuffer=framebuffer0)
            painter1 = Painter(driver, side=1, framebuffer=framebuffer1)

        m.submodules.driver = driver
        m.submodules.painter0 = painter0
        m.submodules.painter1 = painter1

        ports = [
            driver.o_frame,
            driver.o_subframe,
            driver.o_rgb0,
            driver.o_rgb1,
            driver.o_sclk,
            driver.o_addr,
            driver.o_blank,
            driver.o_latch,
            driver.o_rdy,
        ]

        with open('blinker.cpp', 'w') as outf:
            outf.write(cxxrtl.convert(m, ports=ports))
    if args.action == "program":
        from nmigen_boards.icebreaker import *
        p = ICEBreakerPlatformCustom()
        p.add_resources(p.break_off_pmod)
        p.add_resources(p.led_panel_pmod)
        p.build(BoardMapping(), do_program=True)
