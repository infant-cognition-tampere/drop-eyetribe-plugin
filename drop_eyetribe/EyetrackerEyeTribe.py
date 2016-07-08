"""TheEyeTribe plugin for drop."""
from drop.Sensor import Sensor

import glib


class EyeTribeET(Sensor):
    """Plugin class for drop."""

    def __init__(self, rootdir, savedir, on_created, on_error):
        """Constructor."""
        # run the superclass constructor
        super(EyeTribeET, self).__init__()

        self.type = 'Eyetracker'
        self.control_elements = []
        self.device_id = "Eyetribe eyetracker"

        self.on_created = on_created
        self.on_error = on_error

        glib.idle_add(self.on_created, self)

    def trial_started(self, tn, tc):
        """Called when trial has started."""
        return False

    def trial_completed(self, name, tn, tc, misc):
        """Called when trial has completed."""
        return False

    def tag(self, tag):
        """Called when tag needs to be inserted into data."""
        print "TAG %s" % tag

    def action(self, action_id):
        """Perform actions for the control elements defined."""
        print "ET: ACTION"
        return False

    def get_type(self):
        """Get 'type' of eye tracker."""
        return self.type

    def add_data_condition(self, condition):
        """Add data condition."""
        print "ET: ADD DATA CONDITION"
        return False

    def get_device_id(self):
        """Get id of the device."""
        return self.device_id

    def get_control_elements(self):
        """Get control elements."""
        return self.control_elements

    def stop_recording(self):
        """Called when recording should be stopped."""
        print "ET: STOP RECORDING"

    def start_recording(self, rootdir, participant_id, experiment_file,
                        section_id):
        """Called when recording should be started."""
        print "ET: START RECORDING"

    def disconnect(self):
        """Called when disconnect has been requested from GUI."""
        self.emit("clear_screen")
        self.remove_all_listeners()
        return False

    def __del__(self):
        """Destructor."""
        print self.device_id + " disconnected."
