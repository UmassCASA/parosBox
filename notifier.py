import os
import json
from datetime import datetime
import requests

class parosNotifier:
    def __init__(self, config_file):
        # Get config from json
        if not os.path.isfile(config_file):
            raise Exception(f"File {config_file} does not exist")

        # convert json file to dict
        with open(config_file, 'r') as file:
            self.config = json.load(file)

        # fill in slack_webhook secret
        with open(f"secrets/SLACK_WEBHOOK", "r") as file:
            self.config["slack_webhook"] = file.read()

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
