#include <Wire.h>
#include <Sensirion.h>

// State Machine Info
unsigned long previousMillis = 0; 


// Sensirion Related
const int Add1 = 0x40;
Sensirion sens1(Add1);

int16_t signed_sensor_value;
int readingInterval = 100;  // read the Sensirion this often [ms]

// flow related
long volume = 0;
long volumeNoZero = 0;



void setup() {
  // put your setup code here, to run once:
  bool ret = false;
  int rez = 0;
  int16_t calib;
  int16_t calibValue = 0;
  int16_t measurement = 0;
  
  Serial.begin(9600);

  Serial.print("Initial: ");
  Serial.println(ret);
  Serial.print("Sens1: ");
  ret = sens1.connect();
  Serial.println(ret);
  rez = sens1.getResolution();
  Serial.print("Rez1: ");
  Serial.println(rez);
  ret = sens1.setResolution(16);
  Serial.print("Set attempt1: ");
  Serial.println(ret);
  rez = sens1.getResolution();
  Serial.print("Rez1: ");
  Serial.println(rez);
  ret = sens1.setCalibrationValue(0);

  calib = sens1.getCalibrationValue();
  Serial.print("Checing... Calibration for 1 is: ");
  Serial.println(calib);
  ret = sens1.startMeasurementMode();
  Serial.print("Measurement mode for 1 is a: ");
  Serial.println(ret);
  Serial.println("XXXXXXXXXXXX");
 
}

void loop() {

  // update time
  unsigned long currentMillis = millis();
  unsigned long elapsed = currentMillis-previousMillis;
  
  if ((elapsed) > readingInterval){
    signed_sensor_value = sens1.getSensorValue();
    Serial.print(currentMillis);
    Serial.print(",");
    Serial.println(signed_sensor_value);
    previousMillis = currentMillis; //update the current Millis value
  }
}
