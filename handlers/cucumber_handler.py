from dexy.dexy_filter import DexyFilter
from dexy.utils import ansi_output_to_html
import re
import subprocess

class CucumberHandler(DexyFilter):
    """Run cucumber features."""
    INPUT_EXTENSIONS = [".feature"]
    OUTPUT_EXTENSIONS = [".html", ".txt"]
    ALIASES = ["cuke"]
    EXECUTABLE = "cucumber"
    VERSION = "cucumber --version"

    def process(self):
        keys = self.artifact.inputs().keys()
        rb_file = self.artifact.name.replace(".feature", "\.rb")
        matches = [k for k in keys if re.match(re.compile("^%s" % rb_file), k)]

        if len(matches) == 0:
            err_msg = "no file matching %s was found in %s" % (rb_file, keys)
            raise Exception(err_msg)
        if len(matches) > 1:
            err_msg = "too many files matching %s were found in %s: %s" % (rb_file, keys, matches)
            raise Exception(err_msg)

        key = matches[0]
        rb_art = self.artifact.inputs()[key]
        rf = rb_art.filename()
        self.artifact.generate_workfile()
        wf = self.artifact.work_filename()
        command = "%s -r %s %s" % (self.executable(), rf, wf)
        self.log.debug(command)
        env=None
        proc = subprocess.Popen(command, shell=True,
                                cwd=self.artifact.artifacts_dir,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                env=env)
        stdout, stderr = proc.communicate()

        # TODO detect output extension and convert appropriately
        # for now assume HTML
        html = ansi_output_to_html(stdout)
        self.artifact.data_dict['1'] = html

