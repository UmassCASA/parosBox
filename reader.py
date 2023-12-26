import socket
import os
import json
import concurrent.futures
import paros_sensors
import persistqueue
import time
from datetime import datetime
import signal
from notifier import parosNotifier

class parosReader:
    def __init__(self, config_file, notifier):
        # create notifier object
        self.notifier = notifier
        self.notifier.logEvent("Starting ParosBox Sampler...")

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

        # Set graceful shutdown methods
        signal.signal(signal.SIGINT, self.gracefullShutdown)
        signal.signal(signal.SIGTERM, self.gracefullShutdown)
        self.shutting_down = False

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
            elif sensor_type == "Anemometer-1733":
                cur_obj = paros_sensors.Adafruit_Anemometer1733(
                    self.config["box_name"],
                    sensor_dict["id"],
                    sensor_dict["fs"],
                    sensor_dict["input_pin"],
                    sensor_dict["upload"],
                    self.buffer,
                    sensor_dict["log_locally"],
                    self.config["datadir"]
                )
            elif sensor_type == "young_86000":
                cur_obj = paros_sensors.Young_86000(
                    self.config["box_name"],
                    sensor_dict["id"],
                    sensor_dict["upload"],
                    self.buffer,
                    sensor_dict["log_locally"],
                    self.config["datadir"]
                )

                self.sensor_list.append(cur_obj)

    def getSensors(self):
        return self.sensor_list

    def gracefullShutdown(self, *args):
        if not self.shutting_down:
            self.notifier.logEvent("Stopping ParosBox Sampler...")

            self.shutting_down = True

            for sensor in self.sensor_list:
                # ask all sensors to stop sampling
                sensor.stopSampling()

    def isShuttingDown(self):
        return self.shutting_down

def main():
    # Main method
    hostname = socket.gethostname()
    config_file = f"config/{hostname}.json"

    # Reader object for this box
    notifier = parosNotifier(config_file)
    reader = parosReader(config_file, notifier)

    # Launch Threads
    sensor_list = reader.getSensors()

    # Launch Sampling Threads
    sampling_futures = []
    num_sampling_threads = len(sensor_list)  # one thread for each sensor
    sampling_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=num_sampling_threads)
    # store sensor object and future as a tuple so both can be referenced together
    for i in reader.getSensors():
        i.startSampling()  # trigger start sampling on the sensor
        sampling_futures.append((i, sampling_threadpoolexecutor.submit(i.samplingLoop)))  # launch sampling thread

    failCount = 0
    fail_thresh = 8
    fail_hour = datetime.utcnow().hour

    while not reader.isShuttingDown() and failCount < fail_thresh:
        # reset fail stats every hour
        cur_hour = datetime.utcnow().hour
        if cur_hour != fail_hour:
            failCount = 0
            fail_hour = cur_hour

        # check if sampling threads are running
        for future in sampling_futures:
            if future[1].done() or future[1].cancelled():
                # found dead thread
                notifier.logEvent(f"{future[0].getID()} sampling thread has crashed, restarting...: {future[1].result}")
                #print(f"{future[0].getID()} sampling thread has crashed, restarting...: {future[1].result}")
                future[0].startSampling()
                future = (future[0], sampling_threadpoolexecutor.submit(future[0].samplingLoop))
                failCount += 1

        # Wait 5 seconds between main loop
        time.sleep(5)

    if failCount >= fail_thresh:
        notifier.logEvent(f"Shutting down threads due to > {str(fail_thresh)} thread crashes")
        reader.gracefullShutdown()

    # shutdown threads
    sampling_threadpoolexecutor.shutdown()

if __name__ == "__main__":
    main()
