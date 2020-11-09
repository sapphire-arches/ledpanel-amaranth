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

        border_y = (y == 31) | (y == 63) # y == self.frame[0:6]
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

class Painter(Elaboratable):
    LATENCY = 0

    def __init__(self, driver, side):
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

    def elaborate(self, platform):
        m = Module()

        x = self.x
        y = self.y

        is_zero_zero = (x == 0) & (y == self.frame[0:6])
        val_zero_zero = self.frame[1]

        # grad_pos_r = (self.x + self.frame[1:])[0:8]
        # grad_pos_g = (self.y + self.frame[1:])[0:8]
        # grad_pos_b = (self.y + self.x + self.frame[2:])[0:8]
        # pwm_r = PWM(grad_pos_r, self.subframe)
        # pwm_g = PWM(grad_pos_g, self.subframe)
        # pwm_b = PWM(grad_pos_b, self.subframe)

        # rgb = Signal(3)
        # rgb_ff = Signal(3)
        # m.d.comb += rgb.eq(
        #         Cat(Mux(is_zero_zero, val_zero_zero, pwm_r.o_bit), pwm_g.o_bit, pwm_b.o_bit) & Repl(x[2] & y[2], 3))
        # m.d.sync += rgb_ff.eq(rgb)
        # m.d.comb += self.o_rgb.eq(rgb)

        # m.submodules.pwm_r = pwm_r
        # m.submodules.pwm_g = pwm_g
        # m.submodules.pwm_b = pwm_b

        d = Signal(3)
        d_ff = Signal(3)
        m.d.comb += d.eq(
                # Repl((y == 0) & (x == self.frame[0:6]), 3)
                Cat(
                    (x == self.frame[1:7]),
                    (y == 31),
                    0
                )
        )
        m.d.sync += d_ff.eq(d)
        m.d.comb += self.o_rgb.eq(d)

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
            driver = PanelDriver(TEST_CYCLES, 30e6)
        else:
            driver = PanelDriver(Painter.LATENCY, 30e6)

        cd_hsclock = ClockDomain()
        m.domains += cd_hsclock

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
                    o_LOCK=hsclock_lock,
                    i_RESETB=1,
                    i_BYPASS=0
                )
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
            m.submodules.painter0 = dr(Painter(driver, side=0))
            m.submodules.painter1 = dr(Painter(driver, side=1))

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
            driver = PanelDriver(TEST_CYCLES, clk_freq)
            painter0 = CycleAddrTest(TEST_CYCLES, driver, side=0)
            painter1 = CycleAddrTest(TEST_CYCLES, driver, side=1)
        else:
            driver = PanelDriver(Painter.LATENCY, clk_freq)
            painter0 = Painter(driver, side=0)
            painter1 = Painter(driver, side=1)

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
