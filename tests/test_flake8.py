"""Test case which runs flake8."""
import unittest2 as unittest
from subprocess import check_call


class TestFlake8(unittest.TestCase):
    """Test case which runs flake8."""

    def test_flake8(self):
        """Run flake8."""
        check_call(["flake8"])
