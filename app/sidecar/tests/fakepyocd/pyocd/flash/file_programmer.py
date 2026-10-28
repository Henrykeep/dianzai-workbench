import pathlib

import pyocd


class FileProgrammer:
    def __init__(self, session):
        self.session = session

    def program(self, path, base_address=None):
        d = pathlib.Path(path).read_bytes()
        pyocd.LOG.append(("program", path, base_address))
        pyocd.FLASH[:] = d.ljust(max(len(pyocd.FLASH), len(d)), b"\xff")
