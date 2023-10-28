import glob
import serial
from datetime import datetime

class Sensor_6000_16B_IS:
    def __main__(self, serial_num, fs, aa_cutoff):
        self.serial_num = serial_num
        self.sensorPort = None
        self.waitFlag = False  # no response within timeout --> no barometer

        # Validation step
        if fs < 2*fs:
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

            sensorModelNumber = self.__sendCommand('*0100MN')
            if "6000-16B-IS" not in sensorModelNumber:
                continue

            baroSerialNumber = "BLANK"
            while not baroSerialNumber.isnumeric():
                baroSerialNumber = self.__sendCommand('*0100SN')[3:]

            if baroSerialNumber == self.serial_num:
                self.sensorPort = sensorPort
                break

        if self.sensorPort is None:
            raise Exception(f"6000-16B-IS not found with serial {self.serial_num}")
        
        self.waitFlag = True

        # Configure settings on barometer
        fixedSettingsList = ['VR=Q1.03','XM=1','UN=2','MD=0','XN=0','TS=1','GE=1','TJ=0','TF=.00','TP=0','GT=1','GD=0']
        configurableSettingsList = [f'TH={str(fs)},P4;>OK',f'IA={str(aa_cutoff)}']

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
        self.baroPort.timeout = 1.5 * baroSamplePeriod

        # Start P4 sampling
        self.__sendCommand('*0100P4')

    def stopSampling(self):
        # send a command to stop P4 continuous sampling - any command will do
        self.__sendCommand('*0100SN')

    def getSample(self):
        binIn = self.baroPort.readline()
        if not binIn:
            return None

        strIn = binIn.decode()
        in_parts = strIn.split(",")

        cur_timestamp = datetime.strptime(in_parts[1].rstrip(), "%m/%d/%y %H:%M:%S.%f")
        cur_value = in_parts[2].rstrip()

        return cur_timestamp, cur_value

    def __sendCommand(self, strOut):
        strOut = strOut + '\r\n'
        binOut = strOut.encode()
        self.baroPort.write(binOut)

        while True:
            binIn = self.baroPort.readline()
            strIn = binIn.decode()

            if strIn:
                break
            else:
                if not self.waitFlag:
                    break

        return strIn[5:-2]
