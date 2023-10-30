import socket
import os
import json
import concurrent.futures
import paros_sensors
import persistqueue
import time
import influxdb_client

def merge_dicts(dict1, dict2):
    if not isinstance(dict1, dict) or not isinstance(dict2, dict):
        return dict2

    merged = dict1.copy()

    for key, value in dict2.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value

    return merged

class parosReader:
    def __init__(self, config_file, secrets_file):
        # Get config from json
        #! compress these parts?
        if not os.path.isfile(config_file):
            raise Exception(f"File {config_file} does not exist")
        
        if not os.path.isfile(secrets_file):
            raise Exception(f"File {secrets_file} does not exist")

        # convert json file to dict
        with open(config_file, 'r') as file:
            self.config = json.load(file)

        with open(secrets_file, 'r') as file:
            secrets = json.load(file)
            self.config = merge_dicts(self.config, secrets)

        # create buffer queue
        self.buffer = persistqueue.UniqueAckQ('buffer', multithreading=True)

        # create influxdb objects
        self.influx_client = influxdb_client.InfluxDBClient(
            url=self.config["influxdb"]["url"],
            token=self.config["influxdb"]["token"],
            org=self.config["influxdb"]["org"]
            )
        self.influx_write_api = self.influx_client.write_api(write_options=influxdb_client.client.write_api.SYNCHRONOUS)

        # create sensors
        self.__createSensors()

        # create thread executors
        self.sampling_futures = []
        max_sensor_threads = len(self.sensor_list)
        self.sampling_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=max_sensor_threads)

        self.processing_futures = []
        self.num_processing_threads = 1
        self.processing_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=self.num_processing_threads)

        # vars
        self.shutdown = False

    def __createSensors(self):
        # create each sensor object
        self.sensor_list = []
        for sensor_dict in self.config["sensors"]:
            sensor_type = sensor_dict["type"]

            # new sensor types must be added here
            if sensor_type == "6000-16B-IS":
                cur_obj = paros_sensors.Paros_600016BIS(
                    self.config["box_name"],
                    sensor_dict["id"],
                    sensor_dict["fs"],
                    sensor_dict["aa_cutoff"],
                    sensor_dict["upload"],
                    self.buffer,
                    sensor_dict["log_locally"],
                    self.config["datadir"]
                    )

                self.sensor_list.append(cur_obj)

    def __bufferLoop(self):
        while True:
            if self.shutdown:
                break

            # block until item available in queue
            cur_item = self.buffer.get()

            try:
                self.influx_write_api.write(
                    bucket=self.config["influxdb"]["bucket"],
                    org=self.config["influxdb"]["org"],
                    record=cur_item
                    )

                self.buffer.ack(cur_item)
            except:
                self.buffer.nack(cur_item)

    def launchSamplingThreads(self):
        # Create a thread for each sampler
        for i in self.sensor_list:
            i.startSampling()
            self.sampling_futures.append(self.sampling_threadpoolexecutor.submit(i.samplingLoop))

    def killSamplingThreads(self):
        for sensor in self.sensor_list:
            sensor.stopSampling()

        self.sampling_threadpoolexecutor.shutdown(wait=True)

    def launchProcessingThreads(self):
        # Create a thread for each sampler
        for i in range(self.num_processing_threads):
            self.processing_futures.append(self.processing_threadpoolexecutor.submit(self.__bufferLoop))

    def killProcessingThreads(self):
        self.shutdown = True

        self.processing_threadpoolexecutor.shutdown(wait=True)

def main():
    # Main method
    hostname = socket.gethostname()
    config_file = f"config/{hostname}.json"
    secrets_file = f"config/{hostname}-secrets.json"

    reader = parosReader(config_file, secrets_file)
    reader.launchSamplingThreads()
    reader.launchProcessingThreads()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit, Exception):
        reader.killProcessingThreads()
        reader.killSamplingThreads()

if __name__ == "__main__":
    main()