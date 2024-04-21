import datetime
import os

class ParosSensor:

    sampleBufferSize = 20  # this value * Fs is the number of samples kept in a local buffer before sending

    def __init__(self, box_id, sensor_id, data_loc):
        self.box_id = box_id
        self.sensor_id = sensor_id
        self.data_loc = data_loc

        # create data dir if needed
        os.makedirs(os.path.join(self.data_loc, self.sensor_id), exist_ok=True)

    def addSample(self, p):
        # get NTP timestamp
        sys_timestamp = datetime.datetime.now(datetime.UTC)

        # add additional info to sample
        p.time(sys_timestamp)
        p.tag("id", self.sensor_id)

        # add point to data file
        cur_data_file = os.path.join(self.data_loc, self.sensor_id, sys_timestamp.strftime('%Y-%m-%d-%H'))
        serialized_point = p.to_line_protocol()
        with open(cur_data_file, "a+") as f:
            f.write(f"{serialized_point}\n")
