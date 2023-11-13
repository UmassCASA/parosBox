import socket
import os
import json
import persistqueue
import influxdb_client
from influxdb_client.client.exceptions import InfluxDBError
import threading
from notifier import parosNotifier

class parosProcessor:
    def __init__(self, config_file, notifier):
        # create notifier object
        self.notifier = notifier
        self.notifier.logEvent("Starting ParosBox Processor...")

        # Get config from json
        if not os.path.isfile(config_file):
            raise Exception(f"File {config_file} does not exist")

        # convert json file to dict
        with open(config_file, 'r') as file:
            self.config = json.load(file)

        # fill in secrets
        with open(f"secrets/INFLUXDB_TOKEN", "r") as file:
            self.config["influxdb"]["token"] = file.read()

        # create buffer queue
        self.buffer = persistqueue.UniqueAckQ('buffer', multithreading=True)

        # create influxdb objects
        self.influx_client = influxdb_client.InfluxDBClient(
            url=self.config["influxdb"]["url"],
            token=self.config["influxdb"]["token"],
            org=self.config["influxdb"]["org"]
            )
        self.influx_write_api = self.influx_client.write_api(write_options=influxdb_client.client.write_api.SYNCHRONOUS)

    def getNotifier(self):
        return self.notifier

    def bufferLoop(self):
        sendFailed = False

        while True:
            # block until item available in queue
            cur_item = self.buffer.get()

            try:
                self.influx_write_api.write(
                    bucket=self.config["influxdb"]["bucket"],
                    org=self.config["influxdb"]["org"],
                    record=cur_item
                    )

                if sendFailed:
                    self.notifier.logEvent(f"Connection to InfluxDB restored")
                    sendFailed = False
                self.buffer.ack(cur_item)

                # Clear ACKed parts
                self.buffer.clear_acked_data()
            except Exception as e:
                if not sendFailed:
                    self.notifier.logEvent(f"Unable to send data to InfluxDB: {e}")
                    sendFailed = True

                self.buffer.nack(cur_item)

    def cleanBufferThread(self):
        threading.Timer(3600, self.cleanBufferThread).start()
        self.buffer.shrink_disk_usage()

    def isShuttingDown(self):
        return self.shutting_down

def main():
    # Main method
    hostname = socket.gethostname()
    config_file = f"config/{hostname}.json"

    # Reader object for this box
    notifier = parosNotifier(config_file)
    processor = parosProcessor(config_file, notifier)

    # Launch Cleaning Thread
    processor.cleanBufferThread()

    # Main loop in the main thread
    processor.bufferLoop()

if __name__ == "__main__":
    main()
