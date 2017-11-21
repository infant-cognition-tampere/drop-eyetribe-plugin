"""TheEyeTribe plugin for drop."""
from drop.Sensor import Sensor

from threading import Thread
from Queue import Queue
import socket
from select import select
import json
import nudged
import glib
import os
import re
from datetime import datetime
import time
import csv


# Regular expression to match timestamp format given by eyetribe server.
# Compiled initially during import of module.
_timestamp_matcher = re.compile(
    "^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2}) "
    "(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})\."
    "(?P<millisecond>[0-9]{3})$")


def _parse_timestamp(ts):
    m = _timestamp_matcher.match(ts)
    dt = datetime(year=int(m.group('year')),
                  month=int(m.group('month')),
                  day=int(m.group('day')),
                  hour=int(m.group('hour')),
                  minute=int(m.group('minute')),
                  second=int(m.group('second')),
                  microsecond=int(
                      m.group('millisecond')) * 1000)

    return ((time.mktime(dt.timetuple()) * 1000) +
            (dt.microsecond / 1000)) * 1000.0


def _get_validity_from_state(state):
    if state & 0x1 and state & 0x2 and state & 0x4:
        return 0
    return -1


def _convert_gazedata_frame(frame):
    # >LeftEyeNx
    # >LeftEyeNy
    # >LeftEyePosition3dRelativeX
    # >LeftEyePosition3dRelativeY
    #  LeftEyePosition3dRelativeZ ?
    #  LeftEyePosition3dX
    #  LeftEyePosition3dY
    #  LeftEyePosition3dZ
    # >LeftEyePupilDiameter
    # >RightEyeNx
    # >RightEyeNy
    # >RightEyePosition3dRelativeX
    # >RightEyePosition3dRelativeY
    #  RightEyePosition3dRelativeZ ?
    #  RightEyePosition3dX ?
    #  RightEyePosition3dY ?
    #  RightEyePosition3dZ ?
    # >RightEyePupilDiameter
    # >TETTime
    # >ValidityLeftEye
    # >ValidityRightEye
    # >XGazePosLeftEye
    # >XGazePosRightEye
    # >YGazePosLeftEye
    # >YGazePosRightEye

    row = {'XGazePosLeftEye': frame['lefteye']['raw']['x'],
           'YGazePosLeftEye': frame['lefteye']['raw']['y'],
           'XGazePosRightEye': frame['righteye']['raw']['x'],
           'YGazePosRightEye': frame['righteye']['raw']['y'],
           'LeftEyeNx': frame['lefteye_nudged']['raw']['x'],
           'LeftEyeNy': frame['lefteye_nudged']['raw']['y'],
           'RightEyeNx': frame['righteye_nudged']['raw']['x'],
           'RightEyeNy': frame['righteye_nudged']['raw']['y'],
           'LeftEyePosition3dRelativeX':
               1.0 - frame['lefteye']['pcenter']['x'],
           'LeftEyePosition3dRelativeY':
               frame['lefteye']['pcenter']['y'],
           'RightEyePosition3dRelativeX':
               1.0 - frame['righteye']['pcenter']['x'],
           'RightEyePosition3dRelativeY':
               frame['righteye']['pcenter']['y'],
           'LeftEyePupilDiameter': frame['lefteye']['psize'],
           'RightEyePupilDiameter': frame['righteye']['psize'],
           'ValidityBothEyes':
               _get_validity_from_state(frame['state']),
           'TETTime':
               _parse_timestamp(frame['timestamp'])}
    return row


def _convert_json_to_tabdelim(source_filename, dest_filename):
    """Convert file from JSON to CSV format."""
    with open(source_filename, 'r') as json_file:
        json_lines = json_file.readlines()

    json_objects = map(json.loads, json_lines)

    json_frames = filter(lambda x: 'frame' in x, json_objects)
    json_tags = filter(lambda x: 'tag' in x, json_objects)

    frame_dicts = [_convert_gazedata_frame(f['frame']) for f in json_frames]

    frame_keys = list(frozenset(reduce(
        lambda x, y: x + y, [d.keys() for d in frame_dicts])))

    tag_keys = list(frozenset(reduce(
        lambda x, y: x + y, [t['tag'].keys() for t in json_tags])))
    tag_keys = filter(lambda x: x != 'secondary_id', tag_keys)

    # Generate list of start-end tags
    # Assuming that start and end tags always follow each other and that
    # there are even amount of tags
    assert len(json_tags) % 2 == 0

    tags = zip(*[iter([t['tag'] for t in json_tags])]*2)

    # Modify frame dicts to contain tag information where present
    for f in frame_dicts:
        frame_time = f['TETTime'] / (1000 * 1000)
        for t in tags:
            assert t[0]['secondary_id'] == 'start' and \
                t[1]['secondary_id'] == 'end'

            start_time = t[0]['timestamp']
            end_time = t[1]['timestamp']

            if frame_time > start_time and frame_time < end_time:
                tagdict = {k: str(v) for k, v in t[0].iteritems()}
                tagdict.pop('secondary_id')

                f.update(tagdict)

    with open(dest_filename, 'w') as csv_file:
        writer = csv.DictWriter(csv_file,
                                fieldnames=frame_keys + tag_keys,
                                dialect='excel-tab')
        writer.writeheader()
        writer.writerows(frame_dicts)


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

        self.tracker = EyeTribe("localhost", 6555, self._handle_frame_callback)
        self.tracker.start()

        # nudged calibration values
        self.nudged_current_range = None
        self.nudged_domain_r = []
        self.nudged_domain_l = []
        self.nudged_range = []
        self.nudged_transform_r = nudged.Transform(1, 0, 0, 0)
        self.nudged_transform_l = nudged.Transform(1, 0, 0, 0)

        self.collect_data = False

        glib.idle_add(self.on_created, self)

    def _handle_frame_callback(self, frame):
        glib.idle_add(self._handle_gazedata_frame, frame)

    def _inside_aoi(self, x, y, aoi):
        return aoi[0] < x and x < aoi[1] and aoi[2] < y and y < aoi[3]

    def _data_condition_check(self, rx, ry, lx, ly):
        # TODO: Move this function to superclass
        """
        Data condition check.

        Returns True if the condition met, False if not.
        """
        for cond in self.data_conditions:
            if cond["type"] == "aoi":
                if cond["inorout"] == "in" and \
                    (self._inside_aoi(rx, ry, cond["aoi"]) or
                     self._inside_aoi(lx, ly, cond["aoi"])):
                    self.data_conditions = []
                    return True
        return False

    def _handle_gazedata_frame(self, frame):
        # TODO: Create a superclass version of this
        # Parsing
        screen_w = self.tracker.values['screenresw']
        screen_h = self.tracker.values['screenresh']
        gaze_left_x = frame['lefteye']['raw']['x'] / screen_w
        gaze_left_y = frame['lefteye']['raw']['y'] / screen_h
        gaze_right_x = frame['righteye']['raw']['x'] / screen_w
        gaze_right_y = frame['righteye']['raw']['y'] / screen_h

        # Put normalized coordinates back into frame
        frame['lefteye']['raw']['x'] = gaze_left_x
        frame['lefteye']['raw']['y'] = gaze_left_x
        frame['righteye']['raw']['x'] = gaze_right_x
        frame['righteye']['raw']['y'] = gaze_right_y

        # TODO: Do normalization and transforms for avg coordinates as well

        # Nudged transform
        gaze_left_nx, gaze_left_ny = \
            self.nudged_transform_l.transform([gaze_left_x, gaze_left_y])
        gaze_right_nx, gaze_right_ny = \
            self.nudged_transform_r.transform([gaze_right_x, gaze_right_y])

        # Write data to file if recording has started
        frame.update({
            'lefteye_nudged': {'raw': {'x': gaze_left_x, 'y': gaze_left_y}},
            'righteye_nudged': {'raw': {'x': gaze_right_x, 'y': gaze_right_y}}
        })
        if self.collect_data:
            self.collect_file.write(json.dumps({'frame': frame}) + '\n')

        # Calibration & linear transformation section
        if self.nudged_current_range is not None:
            # If tracking both gaze and eyes (as a validity check)
            if frame['state'] & 0x3 != 0:
                self.nudged_range.append(self.nudged_current_range)
                self.nudged_domain_l.append([gaze_left_x, gaze_left_y])
                self.nudged_domain_r.append([gaze_right_x, gaze_right_y])

        # Data condition check
        dc_nudged = self._data_condition_check(gaze_right_nx,
                                               gaze_right_ny,
                                               gaze_left_nx,
                                               gaze_left_ny)
        dc_uncalibrated = self._data_condition_check(gaze_right_x,
                                                     gaze_right_y,
                                                     gaze_left_x,
                                                     gaze_left_y)

        if dc_nudged or dc_uncalibrated:
            self.emit("draw_que_updated")
            self.emit("data_condition_met")

        # Draw eyes and gaze positions
        for eye in ['left', 'right']:
            self.draw_eye(eye, frame[eye + 'eye'], 1.0)

        self.draw_gaze('left', gaze_left_x, gaze_left_y, 1.0)
        self.draw_gaze('right', gaze_right_x, gaze_right_y, 1.0)
        self.draw_gaze('leftN', gaze_left_nx, gaze_left_ny, 1.0,
                       {'r': 1, 'g': 1, 'b': 1})
        self.draw_gaze('rightN', gaze_right_nx, gaze_right_ny, 1.0,
                       {'r': 1, 'g': 1, 'b': 1})

    def trial_started(self, tn, tc):
        """Called when trial has started."""
        return False

    def trial_completed(self, name, tn, tc, misc):
        """Called when trial has completed."""
        return False

    def tag(self, tag):
        """Called when tag needs to be inserted into data."""
        if self.collect_data:
            self.collect_file.write(json.dumps({'tag': tag}) + '\n')

        # check if validity is to be calculated
        if tag["secondary_id"] == "start":

            # go to nudged calibration mode
            if "nudged_point" in tag:

                # Nudged point format: "1.0, 0.5"
                [x, y] = tag["nudged_point"].split(",")
                xf = float(x)
                yf = float(y)
                self.nudged_current_range = [xf, yf]

                # check if previous occurrances of this point exist
                while [xf, yf] in self.nudged_range:
                    # find the index of the element in range
                    ind = self.nudged_range.index([xf, yf])

                    # remove the index from range and domains
                    self.nudged_range.pop(ind)
                    self.nudged_domain_l.pop(ind)
                    self.nudged_domain_r.pop(ind)

        elif tag["secondary_id"] == "end":

            if "nudged_point" in tag:
                self.nudged_current_range = None

                # calculate nudged transform
                print "Calculating nudged calibration for right eye with " + \
                    "vectors: dom[" + str(len(self.nudged_domain_r)) + \
                    "] and range[" + str(len(self.nudged_range))
                self.nudged_transform_r = nudged.estimate(self.nudged_domain_r,
                                                          self.nudged_range)

                print "Calculating new calibration..."
                self.nudged_transform_l = nudged.estimate(self.nudged_domain_l,
                                                          self.nudged_range)
        return False

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
        if self.collect_data:
            self.collect_data = False
            self.collect_file.close()

            _convert_json_to_tabdelim(self.collect_filename + '.json',
                                      self.collect_filename)

    def start_recording(self, rootdir, participant_id, experiment_file,
                        section_id):
        """Called when recording should be started."""
        assert not self.collect_data

        expname = os.path.basename(experiment_file).split('.')[0]
        fname = '%s_%s_%s.gazedata' % (expname,
                                       participant_id,
                                       section_id)
        fname = os.path.join(rootdir, fname)
        json_fname = fname + '.json'

        self.collect_file = open(json_fname, 'w')
        self.collect_filename = fname

        metadata = json.dumps({'metadata': self.tracker.values})
        self.collect_file.write(metadata + '\n')

        self.collect_data = True

    def disconnect(self):
        """Called when disconnect has been requested from GUI."""
        self.tracker.stop()

        self.emit("clear_screen")
        self.remove_all_listeners()
        return False

    def draw_gaze(self, eye, gazepos_x, gazepos_y, opacity,
                  color={'r': 0, 'g': 0, 'b': 1}):
        """Draw one gazepoint."""
        radius = 0.02

        self.emit("add_draw_que",
                  eye,
                  {"type": "circle",
                   "r": color['r'],
                   "g": color['g'],
                   "b": color['b'],
                   "o": opacity,
                   "x": gazepos_x,
                   "y": gazepos_y,
                   "radius": radius})

    def draw_eye(self, eye, frame_eye, opacity):
        """Draw one eye."""
        camera_pos_x = 1.0 - frame_eye['pcenter']['x']
        camera_pos_y = frame_eye['pcenter']['y']
        screen_w = self.tracker.values['screenresw']
        screen_h = self.tracker.values['screenresh']
        gazepos_x = frame_eye['raw']['x'] / screen_w
        gazepos_y = frame_eye['raw']['y'] / screen_h

        point_x = gazepos_x - .5
        point_y = gazepos_y - .5

        ball_radius = 0.075
        iris_radius = 0.03
        pupil_radius = 0.01

        x = 1 - camera_pos_x
        y = camera_pos_y
        self.emit("add_draw_que", eye + "ball",
                  {"type": "circle", "r": 1, "g": 1, "b": 1,
                   "o": opacity, "x": x, "y": y, "radius": ball_radius})

        x = 1 - camera_pos_x + ((ball_radius - iris_radius / 2) * point_x)
        y = camera_pos_y + ((ball_radius - iris_radius / 2) * point_y)
        self.emit("add_draw_que", eye + "iris",
                  {"type": "circle", "r": 0.5, "g": 0.5, "b": 1,
                   "o": opacity, "x": x, "y": y, "radius": iris_radius})
        self.emit("add_draw_que", eye + "pupil",
                  {"type": "circle", "r": 0, "g": 0, "b": 0,
                   "o": opacity, "x": x, "y": y, "radius": pupil_radius})

    def __del__(self):
        """Destructor."""
        print self.device_id + " disconnected."
