"""SRAG Sentinel: SRAG outbreak reports from OpenDATASUS metrics and real-time news."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("srag-sentinel")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"
