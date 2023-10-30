import socket
import os
import json
import concurrent.futures
import paros_sensors
import persistqueue
import time

class parosReader:
    def __init__(self, config_file):
        # Get config from json
        if not os.path.isfile(config_file):
            raise Exception(f"File {config_file} does not exist")

        # convert json file to dict
        with open(config_file, 'r') as file:
            self.config = json.load(file)

        # create buffer queue
        self.buffer = persistqueue.UniqueAckQ('buffer', multithreading=True)

        # create sensors
        self.__createSensors()

        # create thread executors
        self.sampling_futures = []
        max_threads = len(self.sensor_list)
        self.sampling_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)

        self.processing_futures = []
        max_threads = 1
        self.processing_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)

    def __createSensors(self):
        # create each sensor object
        self.sensor_list = []
        for sensor_dict in self.config["sensors"]:
            sensor_type = sensor_dict["type"]

            # new sensor types must be added here
            if sensor_type == "6000-16B-IS":
                cur_obj = paros_sensors.Paros_600016BIS(
                    sensor_dict["id"],
                    sensor_dict["fs"],
                    sensor_dict["aa_cutoff"],
                    sensor_dict["upload"],
                    self.buffer,
                    sensor_dict["log_locally"],
                    self.config["logdir"]
                    )

                self.sensor_list.append(cur_obj)

    def __bufferLoop(self):
        while True:
            # block until item available in queue
            cur_item = self.buffer.get()

            print(cur_item)

            self.buffer.ack(cur_item)

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
        self.processing_futures.append(self.processing_threadpoolexecutor.submit(self.__bufferLoop))

    def killProcessingThreads(self):
        self.processing_threadpoolexecutor.shutdown(wait=False)

def main():
    # Main method
    hostname = socket.gethostname()
    config_file = f"config/{hostname}.json"

    reader = parosReader(config_file)
    reader.launchSamplingThreads()
    reader.launchProcessingThreads()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit, Exception):
        print("Quitting Reader")
        reader.killSamplingThreads()
        reader.killProcessingThreads()

if __name__ == "__main__":
    main()