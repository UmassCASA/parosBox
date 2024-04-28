from ParosSensor import ParosSensor
import serial
import logging

class ParosSerialSensor(ParosSensor):


    def __init__(self, box_id, sensor_id, data_loc, device_file, ser_baud, ser_bytesize, ser_parity, ser_stopbits, ser_timeout):
        # Super constructor
        super().__init__(box_id, sensor_id, data_loc)

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
            logging.critical(f"Unable to open serial port on device {device_file}. Is the device plugged in?")
            exit(1)

    def writeSerial(self, cmd, wait_reply=False):
        # Encode string
        encoded_cmd = self.__encodeCMD(cmd)
        logging.debug(f"Sending to device: {encoded_cmd}")
        self.sensorPort.write(encoded_cmd)  # Send to device

        if wait_reply:
            reply = self.sensorPort.readline()  # Readline blocks until timeout
            logging.debug(f"Received Reply: {reply}")

            try:
                return reply.decode()  # Decode input
            except:
                return None

        return None
    
    def readSerial(self):
        cur_line = self.sensorPort.readline()  # Readline blocks until timeout
        logging.debug(f"Received from Device: {cur_line}")

        try:
            return cur_line.decode()  # Decode input
        except:
            return None
        
    def _getSensorPort(self):
        return self.sensorPort

    def __encodeCMD(self, str):
        outStr = str + '\r\n'
        return outStr.encode()
