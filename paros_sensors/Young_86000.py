import serial
import os
import influxdb_client
import math
from ParosSerialSensor import ParosSerialSensor
from ParosSensor import ParosSensor
import pathlib
from dotenv import load_dotenv
import argparse
import socket

class Young_86000(ParosSerialSensor):

    def __init__(self, box_id, sensor_id, data_loc, device_file):
        super().__init__(
            box_id,
            sensor_id,
            data_loc,
            device_file,
            ser_baud = 9600,
            ser_bytesize = serial.EIGHTBITS,
            ser_parity = serial.PARITY_NONE,
            ser_stopbits = serial.STOPBITS_ONE,
            ser_timeout=1.0
        )

        self.box_id = box_id

        test_line = super().readSerial()
        input_parts = test_line.split(" ")

        if input_parts[0] == self.sensor_id:
            # found sensor
            print(f"Found anemometer with id {sensor_id}")
        else:
            print(f"Unable to find anemometer with id {sensor_id}")

    def __xor_checksum(self, string):
        result = 0
        
        # Finding the index of the asterisk in the string
        asterisk_index = string.find('*')
        
        # Performing XOR operation on characters before the asterisk
        for char in string[:asterisk_index]:
            result ^= ord(char)
        
        return result

    def samplingLoop(self):

        # count failures
        fail_count = 0

        while True:
            try:
                if fail_count > 10:
                    print("Stopping due to too many data failures")
                    self.stopSampling()
                    exit(1)

                strIn = super().readSerial()

                if strIn is None:
                    fail_count += 1
                    continue

                in_parts = strIn.strip().split(" ")

                # verification step
                verification_parts = in_parts[-1].split("*")
                if len(verification_parts) != 2:
                    continue

                if verification_parts[0] != "00":
                    # status code error
                    fail_count += 1
                    continue

                # verify checksum
                checksum = int(verification_parts[1],16)
                calc_checksum = self.__xor_checksum(strIn)
                if calc_checksum != checksum:
                    # continue if bad checksum (this often happens on the first read)
                    fail_count += 1
                    continue

                cur_speed = float(in_parts[1])
                cur_direction = float(in_parts[2])

                # covert to cartesian
                angle_rad = math.radians(cur_direction)
                u = cur_speed * math.cos(angle_rad)
                v = cur_speed * math.sin(angle_rad)

                p = influxdb_client.Point(self.box_id)
                p.field("speed", cur_speed)
                p.field("direction", cur_direction)
                p.field("u", u)
                p.field("v", v)

                ParosSensor.addSample(self, p)

            except KeyboardInterrupt:
                print("Stopping sampling")
                exit(0)

if __name__ == "__main__":
    # load .env file
    file_path = pathlib.Path(__file__).parent.resolve()
    load_dotenv(f"{file_path}/../.env")

    required_envs = [
        "PAROS_DATA_LOCATION"
    ]

    for env_item in required_envs:
        if os.getenv(env_item) is None:
            print(f"Unable to find environment variable {env_item}. Does .env exist?")
            exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("sensor_id", help="Sensor ID Number", type=str)
    parser.add_argument("device", help="Device file for serial connection", type=str)
    args = parser.parse_args()

    cur_sensor = Young_86000(
        socket.gethostname(),
        args.sensor_id,
        os.getenv("PAROS_DATA_LOCATION"),
        args.device
    )
    cur_sensor.samplingLoop()
