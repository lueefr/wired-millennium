"""Legacy import shim for tools/tests. Millennium loads main.lua, not this file."""
import sys
import api
sys.modules[__name__] = api
