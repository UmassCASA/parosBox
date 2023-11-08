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
import signal

class parosReader:
    def __init__(self, config_file):
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

        # Set graceful shutdown methods
        signal.signal(signal.SIGINT, self.gracefullShutdown)
        signal.signal(signal.SIGTERM, self.gracefullShutdown)
        self.shutting_down = False

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

                self.sensor_list.append(cur_obj)

    def startProcessing(self):
        self.processing = True

    def bufferLoop(self):
        sendFailed = False

        while self.processing:
            if self.shutdown:
                break

            # block until item available in queue
            cur_item = self.buffer.get(timeout=1)

            try:
                self.influx_write_api.write(
                    bucket=self.config["influxdb"]["bucket"],
                    org=self.config["influxdb"]["org"],
                    record=cur_item
                    )

                if sendFailed:
                    self.logEvent(f"Connection to InfluxDB restored")
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

    def gracefullShutdown(self, *args):
        self.logEvent("Stopping ParosBox Program...")

        self.shutting_down = True
        self.processing = False

        for sensor in self.sensor_list:
            sensor.stopSampling()

    def isShuttingDown(self):
        return self.shutting_down

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

    # Reader object for this box
    reader = parosReader(config_file)

    # Log startup message
    reader.logEvent("Starting ParosBox Program...")

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

    # Launch Processing Thread
    processing_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    reader.startProcessing()
    processing_future = processing_threadpoolexecutor.submit(reader.bufferLoop)

    # Launch Cleaning Thread
    cleaning_threadpoolexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    cleaning_future = cleaning_threadpoolexecutor.submit(reader.cleanBuffer)

    clean_interval = 3600  # Every hour the sqlite db will be cleaned
    cur_interval = 0  # iterates up to clean_interval

    failCount = 0
    fail_thresh = 8
    fail_hour = datetime.utcnow().hour
    while not reader.isShuttingDown() and failCount < fail_thresh:
        # reset fail stats every hour
        cur_hour = datetime.utcnow().hour
        if cur_hour != fail_hour:
            failCount = 0
            fail_hour = cur_hour

        # Check if it's time to clean buffer
        if not cleaning_future.running() and cur_interval >= clean_interval:
            cleaning_future = cleaning_threadpoolexecutor.submit(reader.cleanBuffer)
            cur_interval = 0

        # check if sampling threads are running
        for future in sampling_futures:
            if future[1].done() or future[1].cancelled():
                # found dead thread
                reader.logEvent(f"{future[0].getID()} sampling thread has crashed, restarting...: {future[1].result}")
                #print(f"{future[0].getID()} sampling thread has crashed, restarting...: {future[1].result}")
                future[0].startSampling()
                future = (future[0], sampling_threadpoolexecutor.submit(future[0].samplingLoop))
                failCount += 1

        # check if processing thread is running
        if processing_future.done() or processing_future.cancelled():
            reader.logEvent(f"Processing thread has crashed, restarting...: {processing_future.result}")
            #print(f"{future[0].getID()} sampling thread has crashed, restarting...: {future[1].result}")
            reader.startProcessing()
            processing_future = processing_threadpoolexecutor.submit(reader.bufferLoop)
            failCount += 1

        cur_interval += 1
        # Wait 1 second between main loop
        time.sleep(1)

    if failCount >= fail_thresh:
        reader.logEvent(f"Shutting down threads due to > {str(fail_thresh)} thread crashes")
        reader.gracefullShutdown()

    # shutdown threads
    processing_threadpoolexecutor.shutdown()
    sampling_threadpoolexecutor.shutdown()
    cleaning_threadpoolexecutor.shutdown()

if __name__ == "__main__":
    main()
