"""This plugin provides TheEyeTribe support for drop."""
from drop_eyetribe.EyetrackerEyeTribe import EyeTribeET
from yapsy.IPlugin import IPlugin
import os.path


class EyeTribePlugin(IPlugin):
    """Interface class for Yapsy."""

    def get_sensor(self, rootdir, savedir, on_rec_cre, on_rec_err):
        """Construct sensor."""
        return EyeTribeET(rootdir, savedir, on_rec_cre, on_rec_err)


def get_plugin():
    """Entry point function for setuptools/distutils."""
    abspath = os.path.abspath(__file__)
    dirname = os.path.dirname(abspath)
    pluginpath = os.path.join(dirname, 'eyetribe.yapsy-plugin')

    return pluginpath, os.path.splitext(abspath)[0]
