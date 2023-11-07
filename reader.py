import socket
import os
import json
import concurrent.futures
import paros_sensors
import persistqueue
import time
import influxdb_client
from influxdb_client.client.exceptions import InfluxDBError
from datetime import datetime
import requests

class parosReader:
    def __init__(self, config_file, secrets_file):
        # Get config from json
        if not os.path.isfile(config_file):
            raise Exception(f"File {config_file} does not exist")

        # convert json file to dict
        with open(config_file, 'r') as file:
            self.config = json.load(file)

        # fill in secrets
        if "influxdb" in self.config and "token" in self.config["influxdb"]:
            self.config["influxdb"]["token"] = self.__readSecret("INFLUXDB_TOKEN")
        
        if "slack_webhook" in self.config:
            self.config["slack_webhook"] = self.__readSecret("SLACK_WEBHOOK")

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

        # vars
        self.shutdown = False

    def __readSecret(self, secret):
        with open(f"secrets/{secret}", "r") as file:
            return file.read()

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

    def bufferLoop(self):
        sendFailed = False

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

                sendFailed = False
                self.buffer.ack(cur_item)

                # Clear ACKed parts
                self.buffer.clear_acked_data()
            except InfluxDBError as e:
                if not sendFailed:
                    self.logEvent(f"Unable to send data to InfluxDB: {e}")
                    sendFailed = True

                self.buffer.nack(cur_item)

    def cleanBuffer(self):
        self.buffer.shrink_disk_usage()

    def getSensors(self):
        return self.sensor_list

    def logEvent(self, str):
        output_str = f"[{self.config['box_name']}] {str}"
        self.__logMessage(output_str)
        self.__sendSlackMessage(output_str)

    def __sendSlackMessage(self, str):
        if self.config["slack_webhook"] != "":
            payload = {"text": str}
            response = requests.post(self.config["slack_webhook"], json.dumps(payload))

            if response.status_code != 200:
                self.__logMessage(f"Slack Webhook Error {response.status_code}")

    def __logMessage(self, str):
        if self.config["logfile"] != "":
            log_file = self.config["logfile"]
            cur_time = datetime.utcnow().isoformat()
            with open(log_file, 'a+') as file:
                file.write(f"[{cur_time}] {str}")

def main():
    # Main method
    hostname = socket.gethostname()
    config_file = f"config/{hostname}.json"
    secrets_file = f"config/{hostname}-secrets.json"

    # Reader object for this box
    reader = parosReader(config_file, secrets_file)

    reader.logEvent("Starting ParosBox Program...")

    # Launch Threads
    sensor_list = reader.getSensors()

    # Launch Sampling Threads
    sampling_futures = []
    num_sampling_threads = len(sensor_list)
    sampling_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=num_sampling_threads)

    for i in reader.getSensors():
        i.startSampling()
        sampling_futures.append((i, sampling_threadpoolexecutor.submit(i.samplingLoop)))

    # Launch Processing Thread
    processing_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    processing_future = processing_threadpoolexecutor.submit(reader.bufferLoop)

    # Create Cleaning Thread
    cleaning_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    cleaning_future = cleaning_threadpoolexecutor.submit(reader.cleanBuffer)

    clean_interval = 3600  # Every hour
    cur_interval = 0

    try:
        while True:
            # Check if it's time to clean buffer
            if not cleaning_future.running() and cur_interval >= clean_interval:
                cleaning_future = cleaning_threadpoolexecutor.submit(reader.cleanBuffer)
                cur_interval = 0

            # check if sampling threads are running
            for future in sampling_futures:
                if future[1].done() or future[1].cancelled():
                    # found dead thread
                    reader.logEvent(f"{future[0].getID()} sampling thread has crashed, restarting...: {future[1].result}")
                    future[0].startSampling()
                    future = (future[0], sampling_threadpoolexecutor.submit(future[0].samplingLoop))

            # check if processing thread is running
            if processing_future.done() or processing_future.cancelled():
                reader.logEvent(f"Processing thread has crashed, restarting...: {processing_future.result}")
                processing_future = processing_threadpoolexecutor.submit(reader.bufferLoop)

            cur_interval += 1
            # Wait 1 second between main loop
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit, Exception):
        reader.logEvent("Stopping ParosBox Program...")

        for sensor in sensor_list:
            sensor.stopSampling()

        sampling_threadpoolexecutor.shutdown(wait=False)
        processing_threadpoolexecutor.shutdown(wait=False)

if __name__ == "__main__":
    main()
