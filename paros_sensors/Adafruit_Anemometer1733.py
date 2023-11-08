import os
import influxdb_client
from pathlib import Path

from datetime import datetime,timedelta
from time import sleep
import threading

from .external.ADS1263 import ADS1263

class Adafruit_Anemometer1733:

    MIN_WIND = 0  # Min wind speed of anemometer
    MAX_WIND = 32.4  # Max wind speed of anemometer

    MIN_V = 0.4  # Min voltage of anemometer output
    MAX_V = 2.0  # Max voltage of anemometer output

    REF = 5.08  # ADC reference voltage

    def __init__(self, box_name, id, fs, adc_input, buffer_on, buffer, log_on, logdir):
        self.box_name = box_name
        self.id = id
        self.fs = fs
        self.adc_input = adc_input
        
        self.buffer_on = buffer_on
        if self.buffer_on:
            self.buffer = buffer

        self.log_on = log_on
        if self.log_on:
            self.logdir = os.path.join(logdir, self.id)

        # initialize ADC
        self.ADC = ADS1263.ADS1263()

        if (self.ADC.ADS1263_init_ADC1('ADS1263_7200SPS') == -1):
            raise Exception("Unable to initialize ADC")

        self.ADC.ADS1263_SetMode(0)

        self.sampleBuffer = []  # buffer of samples before being added to queue
        self.sampleBufferMultiplier = 1  # this value times Fs is the number of samples kept in a local buffer before sending

    def getID(self):
        return self.id
    
    def startSampling(self):
        self.sampling = True
    
    def __sampleThread(self):
        if self.sampling:
            threading.Timer(1 / self.fs, self.__sampleThread).start()
        else:
            return

        # wait for timestamp
        timestamp = datetime.utcnow()

        ADC_value = self.ADC.ADS1263_GetChannalValue(int(self.adc_input))
        ADC_voltage = ADC_value * (self.REF / 0x7fffffff)

        wind_speed = (ADC_voltage - self.MIN_V) / (self.MAX_V - self.MIN_V)
        wind_speed *= self.MAX_WIND - self.MIN_WIND

        if self.buffer_on:
            p = influxdb_client.Point(self.box_name)
            p.tag("id", self.id)
            p.time(timestamp)
            p.field("raw", ADC_value)
            p.field("value", wind_speed)

            self.sampleBuffer.append(p)

            if len(self.sampleBuffer) >= self.fs * self.sampleBufferMultiplier:
                self.buffer.put(self.sampleBuffer)
                self.sampleBuffer = []

        if self.log_on:
            log_line = f"{self.box_name},{self.id},{timestamp.isoformat()},{str(ADC_value)},{str(wind_speed)}"

            hour_time = timestamp.replace(minute=0, second=0, microsecond=0)
            log_file = os.path.join(self.logdir, f"{hour_time.isoformat()}.csv")

            # create directory if it doesn't exist
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)

            with open(log_file, 'a') as output_log:
                output_log.write(log_line + "\n")

    def samplingLoop(self):
        self.__sampleThread()

        while self.sampling:
            sleep(1)

    def stopSampling(self):
        self.sampling = False
        self.ADC.ADS1263_Exit()
