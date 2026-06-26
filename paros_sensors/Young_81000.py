import os
import influxdb_client
from ParosSerialSensor import ParosSerialSensor
from ParosSensor import ParosSensor
import serial
from dotenv import load_dotenv
import argparse
import socket
import pathlib
import logging


class Young_81000(ParosSerialSensor):
    def __init__(self, box_id, sensor_id, data_loc, device_file):
        super().__init__(
            box_id,
            sensor_id,
            data_loc,
            device_file,
            ser_baud=38400,
            ser_bytesize=serial.EIGHTBITS,
            ser_parity=serial.PARITY_NONE,
            ser_stopbits=serial.STOPBITS_ONE,
            ser_timeout=1.0
        )

        self.box_id = box_id
        logging.info(f"Starting RM Young 81000 sampler for sensor id {sensor_id}")

    def samplingLoop(self):
        fail_count = 0

        while True:
            try:
                if fail_count > 10:
                    logging.critical("Stopping due to too many data failures")
                    exit(1)

                strIn = super().readSerial()

                if strIn is None:
                    fail_count += 1
                    continue

                strIn = strIn.strip()
                if not strIn:
                    fail_count += 1
                    continue

                in_parts = strIn.split()

                if len(in_parts) != 5:
                    fail_count += 1
                    continue

                try:
                    speed_3d = float(in_parts[0])
                    azimuth = float(in_parts[1])
                    elevation = float(in_parts[2])
                    speed_of_sound = float(in_parts[3])
                    sonic_temperature = float(in_parts[4])
                except ValueError:
                    fail_count += 1
                    continue

                fail_count = 0

                p = influxdb_client.Point(self.box_id)
                p.field("speed_3d", speed_3d)
                p.field("azimuth", azimuth)
                p.field("elevation", elevation)
                p.field("speed_of_sound", speed_of_sound)
                p.field("sonic_temperature", sonic_temperature)

                ParosSensor.addSample(self, p)

            except KeyboardInterrupt:
                logging.info("Stopping sampling...")
                exit(0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    file_path = pathlib.Path(__file__).parent.resolve()
    load_dotenv(f"{file_path}/../.env")

    if os.getenv("PAROS_DATA_LOCATION") is None:
        logging.critical("Unable to find environment variable PAROS_DATA_LOCATION. Does .env exist?")
        exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("sensor_id", help="Sensor ID Number", type=str)
    parser.add_argument("device", help="Device file for serial connection", type=str)
    args = parser.parse_args()

    cur_sensor = Young_81000(
        socket.gethostname(),
        args.sensor_id,
        os.getenv("PAROS_DATA_LOCATION"),
        args.device
    )
    cur_sensor.samplingLoop()