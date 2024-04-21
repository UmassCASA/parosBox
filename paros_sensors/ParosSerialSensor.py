from ParosSensor import ParosSensor
import serial

class ParosSerialSensor(ParosSensor):

    verbose = False

    def __init__(self, box_id, sensor_id, buffer_loc, backup_loc, device_file, ser_baud, ser_bytesize, ser_parity, ser_stopbits, ser_timeout):
        super().__init__(box_id, sensor_id, buffer_loc, backup_loc)

        # Instance Vars
        self.sensor_id = sensor_id  # serial num of barometer
        self.box_id = box_id  # name of box

        # Create Sensor Port
        self.sensorPort = serial.Serial()
        self.sensorPort.port = device_file

        # close port if open
        if self.sensorPort.isOpen():
            self.sensorPort.close()

        self.sensorPort.baudrate = ser_baud
        self.sensorPort.bytesize = ser_bytesize
        self.sensorPort.parity = ser_parity
        self.sensorPort.stopbits = ser_stopbits
        self.sensorPort.timeout = ser_timeout

        # Open Port
        try:
            self.sensorPort.open()
        except:
            print(f"Unable to open serial port on device {device_file}. Is the device plugged in?")
            exit(1)

    def writeSerial(self, cmd, wait_reply=False):
        encoded_cmd = self.__encodeCMD(cmd)

        if self.verbose:
            print(f"Sending to device: {encoded_cmd}")

        self.sensorPort.write(encoded_cmd)

        if wait_reply:
            reply = self.sensorPort.readline()

            if self.verbose:
                print(f"Received Reply: {reply}")

            try:
                return reply.decode()
            except:
                return None

        return None
    
    def readSerial(self):
        cur_line = self.sensorPort.readline()

        if self.verbose:
            print(f"Received from Device: {cur_line}")

        try:
            return cur_line.decode()
        except:
            return None

    def __encodeCMD(self, str):
        outStr = str + '\r\n'
        return outStr.encode()
