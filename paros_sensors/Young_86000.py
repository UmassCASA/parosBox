import glob
import serial
import os
from datetime import datetime,timezone
import influxdb_client
from pathlib import Path
import math

class Young_86000:
    def __init__(self, box_name, serial_num, buffer_on, buffer, log_on, logdir):
        """
        Constructor for the Young_86000 sensor

        :param box_name: Name of the box (ie. paros1, paros2)
        :type box_name: str
        :param serial_num: Sensor address of the anemometer
        :type serial_num: str
        :param fs: Sampling rate in Hz
        :type fs: int
        :param aa_cutoff: anti-aliasing filter cutoff
        :type aa_cutoff: int
        :param buffer_on: True/False turn on output to persistentqueue buffer
        :type buffer_on: boolean
        :param buffer: Object of persistentqueue
        :type buffer: persistqueue.UniqueAckQ
        :param log_in: True/False turn on output to log file
        :type log_in: boolean
        :param logdir: Logging directory to save log files
        :type logdir: str
        """

        self.serial_num = serial_num  # serial num of barometer
        self.box_name = box_name  # name of box
        self.sensorPort = None  # serial object for sensor port
        self.sampleBuffer = []  # buffer of samples before being added to queue
        self.sampleBufferMultiplier = 1  # this value times Fs is the number of samples kept in a local buffer before sending
        self.fs = 20

        # Get all USB TTYs on the device
        usbPortList = glob.glob('/dev/ttyUSB*')

        for usbPort in usbPortList:
            # Checking usbPort
            sensorPort = serial.Serial()
            sensorPort.port = usbPort

            if sensorPort.isOpen():
                # Close port if already open
                sensorPort.close()

            # Connection parameters
            sensorPort.baudrate = 9600
            sensorPort.bytesize = serial.EIGHTBITS
            sensorPort.parity = serial.PARITY_NONE
            sensorPort.stopbits = serial.STOPBITS_ONE
            sensorPort.timeout = 0.2  # needs to be long enough to wake barometer and get response
            sensorPort.open()

            test_line = sensorPort.read(128)  # read a generous buffer to decode
            split_parts = test_line.split(b"\r")
            if len(split_parts) <= 1:
                continue

            input_line = split_parts[1].decode()
            input_parts = input_line.split(" ")

            if input_parts[0] == self.serial_num:
                # found sensor
                self.sensorPort = sensorPort

        if self.sensorPort is None:
            raise Exception(f"Young 86000 not found with sensor address {self.serial_num}")
        
        # Create log dir variables
        self.log_on = log_on
        self.buffer_on = buffer_on

        if self.buffer_on:
            self.buffer = buffer

        if self.log_on:
            self.logdir = os.path.join(logdir, self.serial_num)
                
    def getID(self):
        """
        Gets the ID (in this case serial number) of the barometer

        :return: Serial # ID of barometer
        :rtype: str
        """

        return self.serial_num
        
    def startSampling(self):
        """
        Starts sampling
        """

        # set sampling bool to true
        self.sampling = True

    def samplingLoop(self):
        """
        This is the main sampling loop that launches as a thread
        """

        def xor_checksum(string):
            result = 0
            
            # Finding the index of the asterisk in the string
            asterisk_index = string.find('*')
            
            # Performing XOR operation on characters before the asterisk
            for char in string[:asterisk_index]:
                result ^= ord(char)
            
            return result

        while self.sampling:
            # wait for line
            binIn = self.sensorPort.read_until(b'\r')

            try:
                strIn = binIn.decode()[:-1]
            except:
                # garbled message
                continue

            in_parts = strIn.split(" ")

            # verify checksum
            verification_parts = in_parts[-1].split("*")
            if len(verification_parts) != 2:
                continue

            if verification_parts[0] != "00":
                # status code error
                raise Exception(f"Status code error for Young 86000 {self.serial_num}")
            
            checksum = int(verification_parts[1],16)
            calc_checksum = xor_checksum(strIn)

            if calc_checksum != checksum:
                # continue if bad checksum (this often happens on the first read)
                continue

            cur_speed = float(in_parts[1].rstrip())
            cur_direction = float(in_parts[2].rstrip())

            # covert to cartesian
            angle_rad = math.radians(cur_direction)
            u = cur_speed * math.cos(angle_rad)
            v = cur_speed * math.sin(angle_rad)

            sys_timestamp = datetime.utcnow()

            sys_timestr = sys_timestamp.isoformat()
            if sys_timestamp.microsecond == 0:
                sys_timestr += ".000000"

            if self.buffer_on:
                p = influxdb_client.Point(self.box_name)
                p.tag("id", self.serial_num)
                p.time(sys_timestamp)
                p.field("speed", cur_speed)
                p.field("direction", cur_direction)
                p.field("u", u)
                p.field("v", v)

                self.sampleBuffer.append(p)

                if len(self.sampleBuffer) >= self.fs * self.sampleBufferMultiplier:
                    self.buffer.put(self.sampleBuffer)
                    self.sampleBuffer = []

            if self.log_on:
                log_line = f"{self.box_name},{self.serial_num},{sys_timestr},{cur_speed},{cur_direction},{u},{v}"

                hour_time = sys_timestamp.replace(minute=0, second=0, microsecond=0)
                log_file = os.path.join(self.logdir, f"{hour_time.isoformat()}.csv")

                # create directory if it doesn't exist
                Path(log_file).parent.mkdir(parents=True, exist_ok=True)

                with open(log_file, 'a') as output_log:
                    output_log.write(log_line + "\n")

    def stopSampling(self):
        """
        Stops sampling - useful if the program is quitting
        """

        self.sampling = False

    def closePort(self):
        """
        Closes serial connection to the barometer
        """

        # Close serial connection
        self.sensorPort.close()
