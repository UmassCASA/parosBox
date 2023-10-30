import glob
import serial
import os
import persistqueue
from datetime import datetime

class Paros_600016BIS:
    def __init__(self, serial_num, fs, aa_cutoff, buffer_on, buffer, log_on, logdir):
        self.serial_num = serial_num
        self.sensorPort = None
        self.waitFlag = False  # no response within timeout --> no barometer

        self.fs = fs
        self.aa_cutoff = aa_cutoff

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

            sensorModelNumber = self.__sendCommand('*0100MN', sensorPort)
            if "6000-16B-IS" not in sensorModelNumber:
                continue

            baroSerialNumber = "BLANK"
            while not baroSerialNumber.isnumeric():
                baroSerialNumber = self.__sendCommand('*0100SN', sensorPort)[3:]

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
            configCmd = '*0100' + configSetting[0:2]
            configResponse = self.__sendCommand(configCmd)

            if configResponse not in fixedSettingsList:
                raise Exception(f"Configuration {configSetting} is not set correctly on {self.serial_num}")

        # check configurable barometer settings, set if not OK
        for configSetting in configurableSettingsList:
            configCmd = '*0100' + configSetting[0:2]
            configResponse = self.__sendCommand(configCmd)
            if configResponse not in configurableSettingsList:
                configCmd = '*0100EW*0100' + configSetting
                configResponse = self.__sendCommand(configCmd)
                if configResponse not in configurableSettingsList:
                    raise Exception(f"Configurable property {configSetting} not set correctly on {self.serial_num}")
        
    def startSampling(self):
        # Set barometer clocks
        utcTimeStr = datetime.utcnow().strftime('%m/%d/%y %H:%M:%S')
        timeSetCmd = '*0100EW*0100GR=' + utcTimeStr
        self.__sendCommand(timeSetCmd)

        # set the serial port timeout for each barometer to be larger than the sample period
        baroSamplePeriod = 1/self.fs
        self.sensorPort.timeout = 1.5 * baroSamplePeriod

        # Start P4 sampling
        self.__sendCommand('*0100P4')

    def samplingLoop(self):
        while True:
            # wait for line
            binIn = self.sensorPort.readline()
            strIn = binIn.decode()

            if "\n" not in strIn:
                # this line was returned after the timeout was reached
                # meaning there is something wrong with the connection
                self.stopSampling()
                return False

            in_parts = strIn.split(",")

            cur_timestamp = datetime.strptime(in_parts[1].rstrip(), "%m/%d/%y %H:%M:%S.%f")
            cur_value = in_parts[2].rstrip()

            sys_timestamp = datetime.utcnow()

            if self.buffer_on:
                sample_dict = {
                    "id": self.serial_num,
                    "value": cur_value,
                    "timestamp": cur_timestamp,
                    "sys_time": sys_timestamp
                }

                self.buffer.put(sample_dict)

            if self.log_on:
                log_line = f"{self.serial_num},{sys_timestamp},{cur_timestamp},{cur_value}"

                hour_time = cur_timestamp.replace(minute=0, second=0, microsecond=0)
                log_file = os.path.join(self.log_dir, f"{hour_time.isoformat()}.csv")
                with open(log_file, 'a') as output_log:
                    output_log.write(log_line)

    def stopSampling(self):
        # send a command to stop P4 continuous sampling - any command will do
        self.__sendCommand('*0100SN')

    def closePort(self):
        # Close serial connection
        self.sensorPort.close()

    def __sendCommand(self, strOut, port = None):
        strOut = strOut + '\r\n'
        binOut = strOut.encode()

        if port is None:
            self.sensorPort.write(binOut)
        else:
            port.write(binOut)

        while True:
            if port is None:
                binIn = self.sensorPort.readline()
            else:
                binIn = port.readline()

            strIn = binIn.decode()

            if strIn:
                break
            else:
                if not self.waitFlag:
                    break

        return strIn[5:-2]
