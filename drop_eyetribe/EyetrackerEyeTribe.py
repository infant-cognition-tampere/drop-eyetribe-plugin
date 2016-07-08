"""TheEyeTribe plugin for drop."""
from drop.Sensor import Sensor

from threading import Thread
from Queue import Queue
import socket
from select import select

import json

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


class EyeTribe(object):
    """
    Class for interfacing with EyeTribe tracker.

    Mostly handles
    serialization with The Eye Tribe server and encapsulates a socket
    thread.
    """

    get_value_keywords = [
        'push',
        'heartbeatinterval',
        'version',
        'trackerstate',
        'framerate',
        'iscalibrated',
        'iscalibrating',
        'screenindex',
        'screenresw',
        'screenresh',
        'screenpsyw',
        'screenpsyh'
    ]

    valid_keywords = get_value_keywords + ['calibresult', 'frame']

    def __init__(self, host, port, cb_frame=None):
        """Constructor."""
        self.host = host
        self.port = port

        self.sockthread = None

        self.cb_frame = cb_frame
        self.values = {}

    def _init_socket(self):
        if self.sockthread is not None:
            return

        self.sockthread = EyeTribeSocket(self.host,
                                         self.port,
                                         self._msg_handler)
        self.sockthread.start()

    def _msg_handler(self, raw_msg):
        # Decode msg
        msg = json.loads(raw_msg)

        # assert msg.get('statuscode') == 200

        if msg.get('category') == 'tracker':
            # Update internal value dict
            self.values.update(msg.get('values', {}))

            # If frame, do a frame callback
            if 'frame' in msg.get('values', {}):
                self.cb_frame(msg.get('values').get('frame'))

    def _gen_request(self, category, request, values):
        # TODO: Some parameter validity checking here
        return {'category': category,
                'request': request,
                'values': values}

    def _gen_set_values_msg(self, values):
        v = dict()
        v.update(values)
        v.update({'version': 2})

        return self._gen_request('tracker', 'set', v)

    def _gen_get_values_msg(self, values):
        return self._gen_request('tracker', 'get', values)

    def _gen_set_push_msg(self, state):
        return self._gen_set_values_msg({'push': state})

    def _start_push(self):
        """Start push mode."""
        self.sockthread.send(json.dumps(self._gen_set_push_msg(True)))

    def _stop_push(self):
        """Stop push mode."""
        # TODO: EyeTribe server does not stop sending data after stop push
        #       request.
        self.sockthread.send(json.dumps(self._gen_set_push_msg(False)))

    def start(self):
        """Start the Eye Tribe."""
        self._init_socket()

        # First request all relevant values from eyetribe server
        self.sockthread.send(json.dumps(self._gen_get_values_msg(
            self.get_value_keywords)))

        # Then start push mode
        self._start_push()

    def stop(self):
        """Stop the Eye Tribe."""
        self._stop_push()
        self.sockthread.stop()

        del self.sockthread
        self.sockthread = None


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
