import glob
import serial
import os
from datetime import datetime,timezone
import influxdb_client
from pathlib import Path
import time

class Paros_600016BIS:
    def __init__(self, box_name, serial_num, fs, aa_cutoff, buffer_on, buffer, log_on, logdir):
        """
        Constructor for the Paros_600016BIS sensor

        :param box_name: Name of the box (ie. paros1, paros2)
        :type box_name: str
        :param serial_num: Serial # of the barometer (used as the ID)
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
        self.waitFlag = False  # no response within timeout --> no barometer
        self.sampleBuffer = []  # buffer of samples before being added to queue
        self.sampleBufferMultiplier = 1  # this value times Fs is the number of samples kept in a local buffer before sending

        self.fs = fs  # sampling rate in Hz
        self.aa_cutoff = aa_cutoff  # anti aliasing cutoff

        # Validation step
        if self.fs < 2*self.aa_cutoff:
            raise Exception(f"fs must be greater than 2x the AA cutoff on {self.serial_num}")

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
            sensorPort.baudrate = 115200
            sensorPort.bytesize = serial.EIGHTBITS
            sensorPort.parity = serial.PARITY_NONE
            sensorPort.stopbits = serial.STOPBITS_ONE
            sensorPort.timeout = 0.2  # needs to be long enough to wake barometer and get response
            sensorPort.open()

            for i in range(2):
                # send this command twice just incase sampling mode was still on
                sensorPort.write(self.__encodeCMD('*0100MN'))

            # read model number
            sensorModelNumber = sensorPort.readline(128)
            try:
                sensorModelNumber = sensorModelNumber.decode()
            except:
                continue

            if "6000-16B-IS" not in sensorModelNumber:
                continue

            baroSerialNumber = "BLANK"
            while not baroSerialNumber.isnumeric():
                sensorPort.write(self.__encodeCMD('*0100SN'))
                baroSerialNumber = sensorPort.readline().decode()[8:-2]

            if baroSerialNumber == self.serial_num:
                self.sensorPort = sensorPort
                break

        if self.sensorPort is None:
            raise Exception(f"6000-16B-IS not found with serial {self.serial_num}")
        
        # Create log dir variables
        self.log_on = log_on
        self.buffer_on = buffer_on

        if self.buffer_on:
            self.buffer = buffer

        if self.log_on:
            self.logdir = os.path.join(logdir, self.serial_num)
        
        # Barometer exists so now we reset waitflag
        self.waitFlag = True

        # Configure settings on barometer
        fixedSettingsList = ['VR=Q1.03','XM=1','UN=2','MD=0','XN=0','TS=1','GE=1','TJ=0','TF=.00','TP=0','GT=1','GD=0']
        configurableSettingsList = [f'TH={str(self.fs)},P4;>OK',f'IA={str(self.aa_cutoff)}']

        # check fixed barometer settings, quit if not OK
        for configSetting in fixedSettingsList:
            configCmd = self.__encodeCMD('*0100' + configSetting[0:2])
            self.sensorPort.write(configCmd)

            configResponse = self.sensorPort.readline().decode()[5:-2]

            if configResponse not in fixedSettingsList:
                raise Exception(f"Configuration {configSetting} is not set correctly on {self.serial_num}")

        # check configurable barometer settings, set if not OK
        for configSetting in configurableSettingsList:
            configCmd = self.__encodeCMD('*0100' + configSetting[0:2])
            self.sensorPort.write(configCmd)

            configResponse = self.sensorPort.readline().decode()[5:-2]
            if configResponse not in configurableSettingsList:
                configCmd = self.__encodeCMD('*0100EW*0100' + configSetting)
                self.sensorPort.write(configCmd)

                configResponse = self.sensorPort.readline().decode()[5:-2]

                if configResponse not in configurableSettingsList:
                    raise Exception(f"Configurable property {configSetting} not set correctly on {self.serial_num}")
                
    def getID(self):
        """
        Gets the ID (in this case serial number) of the barometer

        :return: Serial # ID of barometer
        :rtype: str
        """

        return self.serial_num
        
    def startSampling(self):
        """
        Sends start sampling command to barometer, also resets clock
        """

        # Set barometer clocks
        utcTimeStr = datetime.utcnow().strftime('%m/%d/%y %H:%M:%S')
        timeSetCmd = self.__encodeCMD('*0100EW*0100GR=' + utcTimeStr)
        self.sensorPort.write(timeSetCmd)

        # set the serial port timeout for each barometer to be larger than the sample period
        baroSamplePeriod = 1/self.fs
        self.sensorPort.timeout = 1.5 * baroSamplePeriod

        # set sampling bool to true
        self.sampling = True

        # Start P4 sampling
        self.sensorPort.write(self.__encodeCMD('*0100P4'))
        self.sensorPort.read_until(b'*0001V')

    def samplingLoop(self):
        """
        This is the main sampling loop that launches as a thread
        """

        while self.sampling:
            # wait for line
            binIn = self.sensorPort.readline()

            try:
                strIn = binIn.decode()
            except:
                continue

            in_parts = strIn.split(",")
            
            if in_parts[0] != "*0001V":
                continue

            if len(in_parts) != 3:
                continue

            cur_timestamp = datetime.strptime(in_parts[1].rstrip(), "%m/%d/%y %H:%M:%S.%f")
            cur_value = float(in_parts[2].rstrip())

            sys_timestamp = datetime.utcnow()

            sys_timestr = sys_timestamp.isoformat()
            if sys_timestamp.microsecond == 0:
                sys_timestr += ".000000"

            cur_timestr = sys_timestamp.isoformat()
            if cur_timestamp.microsecond == 0:
                cur_timestr += ".000000"

            if self.buffer_on:
                p = influxdb_client.Point(self.box_name)
                p.tag("id", self.serial_num)
                p.time(sys_timestamp)
                p.field("value", cur_value)
                p.field("baro_time", cur_timestr)

                self.sampleBuffer.append(p)

                if len(self.sampleBuffer) >= self.fs * self.sampleBufferMultiplier:
                    self.buffer.put(self.sampleBuffer)
                    self.sampleBuffer = []

            if self.log_on:
                log_line = f"{self.box_name},{self.serial_num},{sys_timestr},{cur_timestr},{cur_value}"

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
        # send a command to stop P4 continuous sampling - any command will do
        self.sensorPort.write(self.__encodeCMD('*0100SN'))

    def closePort(self):
        """
        Closes serial connection to the barometer
        """

        # Close serial connection
        self.sensorPort.close()

    def __encodeCMD(self, str):
        outStr = str + '\r\n'
        return outStr.encode()
