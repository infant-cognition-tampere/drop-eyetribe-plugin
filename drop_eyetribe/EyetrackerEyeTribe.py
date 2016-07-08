"""TheEyeTribe plugin for drop."""
from drop.Sensor import Sensor

from threading import Thread
from Queue import Queue
import socket
from select import select

import glib


class EyeTribeSocket(Thread):
    """Thread for socket-based communication with EyeTribe server."""

    def __init__(self, host="localhost", port=6555, callback=None):
        """Constructor."""
        super(EyeTribeSocket, self).__init__()

        # Handle messages with callback
        self.callback = callback

        # Create new non-blocking socket and connect
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.sock.setblocking(0)

        self.send_queue = Queue()

    def send(self, msg):
        """
        Put a packet into send queue.

        Thread main loop will process it in sending phase.
        """
        # TODO MAYBE: Check message validity before sending
        # Put message into send_queue
        self.send_queue.put(msg)

    def run(self):
        """Main loop of the socket thread."""
        partial_data = ""

        while self.should_run:
            # Get stuff from send_queue and send
            while not self.send_queue.empty():
                msg = self.send_queue.get(False)
                self.sock.send(msg)
                self.send_queue.task_done()

            # Select from sockets
            # TODO: Somewhat hacky solution to use 0.01 timeout,
            #       examine the possibility to use "signals."
            read_sockets, write_sockets, err_sockets = \
                select([self.sock], [], [], 0.01)

            for sock in read_sockets:
                if sock == self.sock:
                    read_data = sock.recv(512)
                    if not read_data:
                        raise IOError

                    read_data = partial_data + read_data

                    msgs = read_data.split('\n')
                    for msg in msgs[:-1]:
                        # Do a callback for received messages
                        if self.callback is not None:
                            self.callback(msg)

                    partial_data = msgs[-1]

    def start(self):
        """Start the socket thread."""
        self.should_run = True
        return super(EyeTribeSocket, self).start()

    def stop(self):
        """Cause the socket loop to exit."""
        self.should_run = False


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
