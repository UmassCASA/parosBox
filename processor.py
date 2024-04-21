import influxdb_client
import pathlib
from dotenv import load_dotenv
import os
import datetime
import pickle
import socket
import json
import logging
from time import sleep

class parosProcessor:

    pointer_path = 'pointer.pickle'
    maximum_upload = 600
    sending_frequency = 1  # number of seconds to send data

    def __init__(self, data_loc, influx_host, influx_org, influx_bucket, influx_token):
        self.data_loc = data_loc
        self.influx_bucket = influx_bucket

        # create influxdb objects
        self.influx_client = influxdb_client.InfluxDBClient(
            url=influx_host,
            token=influx_token,
            org=influx_org
        )
        self.influx_write_api = self.influx_client.write_api(write_options=influxdb_client.client.write_api.SYNCHRONOUS, debug=True)

        # get list of sensors
        self.sensors = []
        with open(f'sensor_configs/{socket.gethostname()}.json', 'r') as f:
            sensors_json = json.load(f)['sensors']
            for sensor in sensors_json:
                self.sensors.append(sensor['sensor_id'])

        # create pointer file if needed (initial or reset)
        if not os.path.isfile(self.pointer_path) or os.path.getsize(self.pointer_path) == 0:
            cur_time = datetime.datetime.now(datetime.UTC)
            file_hour = cur_time.strftime('%Y-%m-%d-%H')

            for sensor in self.sensors:
                self.setPointer(sensor, file_hour, 1)

    def getPointer(self, sensor_id = None):
        if os.path.isfile(self.pointer_path) and os.path.getsize(self.pointer_path) > 0:
            with open(self.pointer_path, 'rb') as f:
                cur_pointer = pickle.load(f)
                if sensor_id is None:
                    return cur_pointer
                else:
                    return cur_pointer[sensor_id]
        else:
            return {}

    def setPointer(self, sensor_id, hour, offset):
        cur_pointer = self.getPointer()
        cur_pointer[sensor_id] = [hour, offset]
        with open(self.pointer_path, 'wb') as f:
            pickle.dump(cur_pointer, f)

    def __getLatestData(self, cur_path, cur_offset):
        with open(cur_path, 'r') as f:
            f.seek(cur_offset)

            output_str = ""
            line_counter = 0
            while True:
                if line_counter > self.maximum_upload:
                    break

                lp_str = f.readline()
                if not lp_str:
                    # no more lines
                    break

                output_str += lp_str
                line_counter += 1
                cur_offset += len(lp_str)

        return output_str,cur_offset,line_counter

    def __processSensor(self, sensor):
        cur_sensor_dir = os.path.join(self.data_loc, sensor)
        cur_file,cur_offset = self.getPointer(sensor)
        cur_path = os.path.join(cur_sensor_dir, cur_file)

        # this stored the output line-protocol for the given sensors during this loop
        output_lp = ""

        #print("-----------")
        #print(sensor)
        #print(cur_file)
        #print(cur_offset)
        #print("-----------")

        cur_pointer_time = datetime.datetime.strptime(cur_file, '%Y-%m-%d-%H')

        num_lines = 0

        if os.path.isfile(cur_path):
            output_lp,cur_offset,num_lines = self.__getLatestData(cur_path, cur_offset)

        if output_lp:
            try:
                # Send 'em off!
                self.influx_write_api.write(
                    bucket = self.influx_bucket,
                    record = output_lp
                )

                print(f"Sending {num_lines} of line-protocol")

                self.setPointer(sensor, cur_file, cur_offset)
            except:
                pass
        else:
            # no new output
            if self.__getHourOnlyUTCNow() > cur_pointer_time:
                # we're in the future now
                cur_pointer_time += datetime.timedelta(hours=1)
                cur_file = cur_pointer_time.strftime('%Y-%m-%d-%H')
                cur_offset = 0

            self.setPointer(sensor, cur_file, cur_offset)

        return num_lines

    def __getHourOnlyUTCNow(self):
        return datetime.datetime.now(datetime.UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)

    def processorLoop(self):
        while True:
            try:
                loop_start_time = datetime.datetime.now()
                max_num_lines = 0

                # loop through each sensor and poll files
                for sensor in self.sensors:
                    cur_num_lines = self.__processSensor(sensor)
                    if cur_num_lines > max_num_lines:
                        max_num_lines = cur_num_lines

                if max_num_lines < self.maximum_upload:
                    while datetime.datetime.now() < loop_start_time + datetime.timedelta(seconds=1):
                        sleep(0.1)
            except KeyboardInterrupt:
                print("Stopping processor")
                exit(0)

def main():
    logging.basicConfig(level=logging.DEBUG)

    # Read .env file
    file_path = pathlib.Path(__file__).parent.resolve()
    load_dotenv(f"{file_path}/.env")

    required_envs = [
        "PAROS_DATA_LOCATION",
        "PAROS_INFLUXDB_HOST",
        "PAROS_INFLUXDB_ORG",
        "PAROS_INFLUXDB_BUCKET",
        "PAROS_INFLUXDB_TOKEN"
    ]

    for env_item in required_envs:
        if os.getenv(env_item) is None:
            print(f"Unable to find environment variable {env_item}. Does .env exist?")
            exit(1)

    # Create processor
    processor = parosProcessor(
        os.getenv("PAROS_DATA_LOCATION"),
        os.getenv("PAROS_INFLUXDB_HOST"),
        os.getenv("PAROS_INFLUXDB_ORG"),
        os.getenv("PAROS_INFLUXDB_BUCKET"),
        os.getenv("PAROS_INFLUXDB_TOKEN")
    )

    # Main loop in the main thread
    processor.processorLoop()

if __name__ == "__main__":
    main()
