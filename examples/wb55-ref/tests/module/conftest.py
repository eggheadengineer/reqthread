import ctypes
import os

import pytest


@pytest.fixture(scope="session")
def lib():
    return ctypes.CDLL(os.environ["WB55_LIB"])
