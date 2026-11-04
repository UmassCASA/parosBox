from ParosSensor import ParosSensor
from ParosSerialSensor import ParosSerialSensor
import serial
import datetime
import influxdb_client
import argparse
import os
from dotenv import load_dotenv
import socket
import pathlib
import logging
import math

class Paros_MET5(ParosSerialSensor):

    def __init__(self, box_id, sensor_id, data_loc, device_file):
        # Super constructor
        super().__init__(
            box_id,
            sensor_id,
            data_loc,
            device_file,
            ser_baud = 115200,
            ser_bytesize = serial.EIGHTBITS,
            ser_parity = serial.PARITY_NONE,
            ser_stopbits = serial.STOPBITS_ONE,
            ser_timeout=1.0
        )

        # Define Instance Vars
        self.box_id = box_id

        # Verify serial number of barometer
        # This also resets the barometer to a normal state if it was left sampling
        for i in range(2):
            # Do this twice because sometimes the barometer is caught in an already sampling state
            self.sensorPort.reset_input_buffer()
            baroSerialNumReply = super().writeSerial('*0100SN', wait_reply=True)

        if baroSerialNumReply and baroSerialNumReply.strip().startswith("*0001SN="):
            baroSerialNum = baroSerialNumReply.strip().split("=")[1]
            if baroSerialNum == sensor_id:
                logging.info(f"Found barometer with serial number {baroSerialNum}")
            else:
                logging.critical(f"Barometer serial number {baroSerialNum} does not match {sensor_id}")
                self.sensorPort.close()
                exit(1)
        else:
            logging.critical(f"Barometer on device {device_file} either did not respond or returned a malformed response")
            self.sensorPort.close()
            exit(1)

    def samplingLoop(self):

        # Clock writes take about two seconds on M5.00 firmware. Allow the
        # complete reply to arrive before retrying; keep sampling at 1 second.
        normal_timeout = self.sensorPort.timeout
        clock_ok = False
        time_reply = None
        try:
            self.sensorPort.timeout = 5.0
            for i in range(2):
                utcTimeStr = datetime.datetime.now(datetime.UTC).strftime('%m/%d/%y %H:%M:%S')
                self.sensorPort.reset_input_buffer()
                time_reply = super().writeSerial('*0100EW*0100GR=' + utcTimeStr, wait_reply=True)

                try:
                    if not time_reply or not time_reply.strip().startswith('*0001GR='):
                        raise ValueError("Missing clock response")
                    baro_time = datetime.datetime.strptime(
                        time_reply.strip().split("=", 1)[1], "%m/%d/%y %H:%M:%S"
                    )
                    target_time = datetime.datetime.strptime(utcTimeStr, "%m/%d/%y %H:%M:%S")
                    clock_ok = abs((baro_time - target_time).total_seconds()) <= 2
                except ValueError:
                    clock_ok = False

                if clock_ok:
                    break
        finally:
            self.sensorPort.timeout = normal_timeout

        if not clock_ok:
            logging.critical("MET5 was unable to set time; last reply: %r", time_reply)
            self.stopSampling()
            exit(1)

        # Start P4 sampling (pressure, relative humidity, and air temperature)
        logging.info("Starting Sampling...")
        super().writeSerial('*0100P4')

        # count failures
        fail_count = 0

        while True:
            try:
                # Kill the sampler if there are too many failures
                if fail_count > 10:
                    logging.critical("Stopping due to too many data failures")
                    self.stopSampling()
                    exit(1)

                # Read line
                strIn = super().readSerial()

                # strIn is none if it was unable to decode
                if strIn is None:
                    fail_count += 1
                    continue

                # strip whitespace
                strIn = strIn.strip()

                # split up line
                in_parts = strIn.split(",")
                
                # Verify that this is actually a sample line
                if in_parts[0] != "*0001V":
                    fail_count += 1
                    continue

                # Verify length of line
                if len(in_parts) != 5:
                    fail_count += 1
                    continue

                # MET5 record: header, timestamp, pressure (hPa), RH (%), air temp (C)
                try:
                    baro_timestamp = datetime.datetime.strptime(in_parts[1], "%m/%d/%y %H:%M:%S.%f")
                    cur_value = float(in_parts[2])
                    relative_humidity = float(in_parts[3])
                    air_temperature = float(in_parts[4])
                    if not all(math.isfinite(value) for value in
                               (cur_value, relative_humidity, air_temperature)):
                        raise ValueError("Non-finite measurement")
                except ValueError:
                    fail_count += 1
                    continue

                fail_count = 0

                # form influxdb point data structure
                p = influxdb_client.Point(self.box_id)
                p.field("value", cur_value)
                p.field("relative_humidity", relative_humidity)
                p.field("air_temperature", air_temperature)
                # Barometer time is stored as a field, not the primary time field
                p.field("baro_time", self.__getTimeStr(baro_timestamp))

                ParosSensor.addSample(self, p)

            except KeyboardInterrupt:
                logging.info("Stopping sampling...")
                self.stopSampling()
                exit(0)

    def stopSampling(self):
        try:
            super().writeSerial('*0100SN', wait_reply=True)
        finally:
            self.sensorPort.close()

    def __getTimeStr(self, in_time):
        timeStr = in_time.isoformat()
        if in_time.microsecond == 0:
            timeStr += ".000000"

        return timeStr

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # load .env file
    file_path = pathlib.Path(__file__).parent.resolve()
    load_dotenv(f"{file_path}/../.env")

    # Required environment vars
    required_envs = [
        "PAROS_DATA_LOCATION"
    ]

    for env_item in required_envs:
        if os.getenv(env_item) is None:
            logging.critical(f"Unable to find environment variable {env_item}. Does .env exist?")
            exit(1)

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("sensor_id", help="Sensor ID Number", type=str)
    parser.add_argument("device", help="Device file for serial connection", type=str)
    args = parser.parse_args()

    # Create sensor object and start sampling
    cur_sensor = Paros_MET5(
        socket.gethostname(),
        args.sensor_id,
        os.getenv("PAROS_DATA_LOCATION"),
        args.device
    )
    cur_sensor.samplingLoop()
