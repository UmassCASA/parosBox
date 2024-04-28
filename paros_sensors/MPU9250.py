import serial
import os
import influxdb_client
from ParosSerialSensor import ParosSerialSensor
from ParosSensor import ParosSensor
import pathlib
from dotenv import load_dotenv
import argparse
import socket
import RPi.GPIO as GPIO
from time import sleep
import logging

class MPU9250(ParosSerialSensor):

    def __init__(self, box_id, sensor_id, data_loc, device_file, modePin):
        # Enable IMU mode on the ESP32
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(modePin, GPIO.OUT)
        GPIO.output(modePin, GPIO.LOW)

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

        # Reset ESP32
        super()._getSensorPort().setDTR(False)
        sleep(0.1)
        super()._getSensorPort().setDTR(True)
        
        # Let the ESP32 boot up (waits until it sees a sample)
        in_parts = []
        bootup_limit = 30
        i = 1
        while len(in_parts) != 7:
            if i > bootup_limit:
                logging.critical("ESP32 did not come up properly after reset")
                exit(1)

            strIn = super().readSerial()
            if strIn is not None:
                in_parts = strIn.split(",")

            i += 1

        self.box_id = box_id

    def samplingLoop(self):

        # count failures
        fail_count = 0

        while True:
            try:
                if fail_count > 10:
                    logging.critical("Stopping due to too many data failures")
                    self.stopSampling()
                    exit(1)

                strIn = super().readSerial()

                if strIn is None:
                    fail_count += 1
                    continue

                in_parts = strIn.strip().split(",")

                # Validation
                if len(in_parts) != 7:
                    fail_count += 1
                    continue

                p = influxdb_client.Point(self.box_id)
                p.field("imu_time", float(in_parts[0]))
                p.field("accelX", float(in_parts[1]))
                p.field("accelY", float(in_parts[2]))
                p.field("accelZ", float(in_parts[3]))
                p.field("gyroX", float(in_parts[4]))
                p.field("gyroY", float(in_parts[5]))
                p.field("gyroZ", float(in_parts[6]))

                ParosSensor.addSample(self, p)

            except KeyboardInterrupt:
                logging.info("Stopping sampling")
                GPIO.cleanup()
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
            logging.critical(f"Unable to find environment variable {env_item}. Does .env exist?")
            exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("sensor_id", help="Sensor ID Number", type=str)
    parser.add_argument("device", help="Device file for serial connection", type=str)
    parser.add_argument("mode_gpio_pin", help="Physical pin number for GPIO pin to set mode", type=int)
    args = parser.parse_args()

    cur_sensor = MPU9250(
        socket.gethostname(),
        args.sensor_id,
        os.getenv("PAROS_DATA_LOCATION"),
        args.device,
        args.mode_gpio_pin
    )
    cur_sensor.samplingLoop()
