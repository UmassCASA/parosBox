import persistqueue
import datetime
import os

class ParosSensor:

    sampleBufferSize = 20  # this value * Fs is the number of samples kept in a local buffer before sending

    def __init__(self, box_id, sensor_id, buffer_loc, backup_loc):
        self.box_id = box_id
        self.sensor_id = sensor_id
        self.backup_loc = backup_loc

        # Initialize Buffer
        self.buffer = persistqueue.Queue(buffer_loc)
        self.sampleBuffer = []  # buffer of samples before being added to queue

    def addSample(self, p):
        # get NTP timestamp
        sys_timestamp = datetime.datetime.now(datetime.UTC)

        # add additional info to sample
        p.time(sys_timestamp)
        p.tag("id", self.sensor_id)

        # add to internal buffer
        self.sampleBuffer.append(p)

        # add to backup file
        hour_timestamp = sys_timestamp.replace(minute=0, second=0, microsecond=0)
        cur_backup_file = os.path.join(self.backup_loc, f"{hour_timestamp.isoformat()}.txt")
        serialized_point = p.to_line_protocol()
        with open(cur_backup_file, "a+") as f_backup:
            # Create newline if needed
            f_backup.write(f"{serialized_point}\n")

        # send to external buffer
        if len(self.sampleBuffer) >= self.sampleBufferSize:
            self.buffer.put(self.sampleBuffer)
            self.buffer.task_done()
            self.sampleBuffer = []
