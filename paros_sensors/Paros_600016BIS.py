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

class Paros_600016BIS(ParosSerialSensor):

    def __init__(self, box_id, sensor_id, buffer_loc, backup_loc, device_file):
        super().__init__(
            box_id,
            sensor_id,
            buffer_loc,
            backup_loc,
            device_file,
            ser_baud = 115200,
            ser_bytesize = serial.EIGHTBITS,
            ser_parity = serial.PARITY_NONE,
            ser_stopbits = serial.STOPBITS_ONE,
            ser_timeout=1.0
        )

        self.box_id = box_id

        # Verify serial number
        for i in range(2):
            # Do this twice because sometimes the barometer is caught in an already sampling state
            baroSerialNumReply = super().writeSerial('*0100SN', wait_reply=True)

        if "=" in baroSerialNumReply:
            baroSerialNum = baroSerialNumReply.strip().split("=")[1]
            if baroSerialNum == sensor_id:
                print(f"Found barometer with serial number {baroSerialNum}")
            else:
                print(f"Barometer serial number {baroSerialNum} does not match {sensor_id}")
                exit(1)
        else:
            print(f"Barometer on device {device_file} either did not respond or returned a malformed response")
            exit(1)

    def samplingLoop(self):

        # Set barometer clocks
        utcTimeStr = datetime.datetime.now(datetime.UTC).strftime('%m/%d/%y %H:%M:%S')
        time_reply = super().writeSerial('*0100EW*0100GR=' + utcTimeStr, wait_reply=True)
        if time_reply.strip().split("=")[1].split(" ")[0] != utcTimeStr.split(" ")[0]:
            print("Barometer was unable to set time")
            exit(1)

        # Start P4 sampling
        print("Starting Sampling...")
        super().writeSerial('*0100P4')

        # count failures
        fail_count = 0

        while True:
            try:
                if fail_count > 10:
                    print("Stopping due to too many data failures")
                    self.stopSampling()
                    exit(1)

                strIn = super().readSerial().strip()

                if strIn is None:
                    fail_count += 1
                    continue

                strIn = strIn.strip()

                in_parts = strIn.split(",")
                
                # Verify that this is actually a sample line
                if in_parts[0] != "*0001V":
                    fail_count += 1
                    continue

                # Verify length of line
                if len(in_parts) != 3:
                    fail_count += 1
                    continue

                # get barometer timestamp
                baro_timestamp = datetime.datetime.strptime(in_parts[1], "%m/%d/%y %H:%M:%S.%f")
                # get barometer value
                cur_value = float(in_parts[2])

                # form influxdb point data structure
                p = influxdb_client.Point(self.box_id)
                p.field("value", cur_value)
                p.field("baro_time", self.__getTimeStr(baro_timestamp))

                ParosSensor.addSample(self, p)

            except KeyboardInterrupt:
                print("Stopping sampling")
                self.stopSampling()
                exit(0)

    def stopSampling(self):
        super().writeSerial('*0100SN', wait_reply=True)

    def __getTimeStr(self, in_time):
        timeStr = in_time.isoformat()
        if in_time.microsecond == 0:
            timeStr += ".000000"

        return timeStr

if __name__ == "__main__":
    # load .env file
    file_path = pathlib.Path(__file__).parent.resolve()
    load_dotenv(f"{file_path}/../.env")

    buffer_loc = os.getenv('PAROS_BUFFER_LOCATION')
    if buffer_loc is None:
        print(".env file is missing or BUFFER_LOC not defined")
        exit(1)

    backup_loc = os.getenv('PAROS_BACKUP_LOCATION')
    if backup_loc is None:
        print(".env file is missing or BACKUP_LOC not defined")
        exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("sensor_id", help="Sensor ID Number", type=str)
    parser.add_argument("device", help="Device file for serial connection", type=str)
    args = parser.parse_args()

    cur_sensor = Paros_600016BIS(socket.gethostname(), args.sensor_id, buffer_loc, backup_loc, args.device)
    cur_sensor.samplingLoop()
