# This is heavily based on tests/utils.py from amaranth, and is thus licensed
# under the BSD-2-clause as with the rest of amaranth
import os
import re
import shutil
import subprocess
import textwrap
import traceback
import unittest
from contextlib import contextmanager

from amaranth.hdl.ast import *
from amaranth.hdl.ir import *
from amaranth.back import rtlil
from amaranth._toolchain import require_tool


__all__ = ["FHDLTestCase"]


class FHDLTestCase(unittest.TestCase):
    def assertFormal(self, spec, mode="bmc", depth=1):
        stack = traceback.extract_stack()
        for frame in reversed(stack):
            if os.path.dirname(__file__) not in frame.filename:
                break
            caller = frame

        spec_root, _ = os.path.splitext(caller.filename)
        spec_dir = os.path.dirname(spec_root)
        spec_name = "{}_{}".format(
            os.path.basename(spec_root).replace("test_", "spec_"),
            caller.name.replace("test_", "")
        )

        # The sby -f switch seems not fully functional when sby is reading from stdin.
        if os.path.exists(os.path.join(spec_dir, spec_name)):
            shutil.rmtree(os.path.join(spec_dir, spec_name))

        if mode == "hybrid":
            # A mix of BMC and k-induction, as per personal communication with Claire Wolf.
            script = "setattr -unset init w:* a:amaranth.sample_reg %d"
            mode   = "bmc"
        else:
            script = ""

        config = textwrap.dedent("""\
        [options]
        mode {mode}
        depth {depth}
        wait on

        [engines]
        smtbmc

        [script]
        read_ilang top.il
        prep
        {script}

        [file top.il]
        {rtlil}
        """).format(
            mode=mode,
            depth=depth,
            script=script,
            rtlil=rtlil.convert(Fragment.get(spec, platform="formal"))
        )
        with subprocess.Popen([require_tool("sby"), "-f", "-d", spec_name], cwd=spec_dir,
                              universal_newlines=True,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
            stdout, stderr = proc.communicate(config)
            if proc.returncode != 0:
                self.fail("Formal verification failed:\n" + stdout)
