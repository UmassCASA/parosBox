/*Following installations are needed

MPU9250 (IMU) Library: https://github.com/sparkfun/SparkFun_MPU-9250-DMP_Arduino_Library/tree/master

ESP32 ARDUINO SDK: https://github.com/espressif/arduino-esp32

*/

#include <Arduino.h>
#include <SparkFunMPU9250-DMP.h>

#define SerialPort Serial

MPU9250_DMP imu;

int intPin = 26;
int modePin = 25;
bool imuMode;

uint64_t timestamp;
bool new_timestamp;

void isrGpio() {
    timestamp = esp_timer_get_time();
    new_timestamp = true;
}

void setup()
{
  SerialPort.begin(115200);

  pinMode(modePin, INPUT_PULLUP);

  if (digitalRead(modePin) == HIGH) {
    // Clock Drift Calc Mode
    imuMode = false;

    // Interrupt ping setup
    new_timestamp = false;
    pinMode(intPin, INPUT_PULLUP);
    attachInterrupt(intPin, isrGpio, FALLING);
  } else {
    // IMU mode
    imuMode = true;

    while (imu.begin() != INV_SUCCESS)
    {
      SerialPort.println("Unable to communicate with MPU-9250, waiting 5 secs");
      delay(5000);
    }

    imu.setSensors(INV_XYZ_GYRO | INV_XYZ_ACCEL);     // Enable gyroscope and accelerometer
    imu.setGyroFSR(2000);                             // Set gyro to 2000 dps
    imu.setAccelFSR(8);                               // Set accel to +/-8g
    imu.setLPF(98);                                   // Set LPF corner frequency to 98Hz
    imu.setSampleRate(20);                            // Set sample rate to 20Hz
  }
}

void loop() 
{
  if (imuMode && imu.dataReady()) {
    // IMU loop
    imu.update(UPDATE_ACCEL | UPDATE_GYRO);
    printIMUData();
  } else {
    if (new_timestamp) {
      // Timestamp Loop
      new_timestamp = false;
      SerialPort.println(timestamp);
    }
  }
}

void printIMUData(void)
{
  float accelX = imu.calcAccel(imu.ax);
  float accelY = imu.calcAccel(imu.ay);
  float accelZ = imu.calcAccel(imu.az);
  float gyroX = imu.calcGyro(imu.gx);
  float gyroY = imu.calcGyro(imu.gy);
  float gyroZ = imu.calcGyro(imu.gz);

  SerialPort.printf("%i,%f,%f,%f,%f,%f,%f", imu.time, accelX, accelY, accelZ, gyroX, gyroY, gyroZ);
  SerialPort.println();
}
