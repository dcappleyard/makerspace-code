
/*******************************************************************************
 * Purpose:  Example code for the I2C communication with Sensirion Liquid
 *           Flow Sensors
 *
 *           Read measurements from the sensor
 ******************************************************************************/

#include <Wire.h> // Arduino library for I2C
#include <Adafruit_RGBLCDShield.h>
#include <utility/Adafruit_MCP23017.h>
#include <Servo.h>


//setup for Servo
Servo myservo;  // create servo object to control a servo

int manualFlag = 0;  //start in automatic
int ZEROFLOW = 95;  // approximate value of servo for no flow
int pos = ZEROFLOW;

//setup for flow
int setpoint = 600;
int window = 150; //window for no adjustment


//Setup for the Sensirion
const int ADDRESS = 0x48; // Standard address for Liquid Flow Sensors (#2 Bauman)
const bool VERBOSE_OUTPUT = true; // set to false for less verbose output

// EEPROM Addresses for factor and unit of calibration fields 0,1,2,3,4.
const uint16_t SCALE_FACTOR_ADDRESSES[] = {0x2B6, 0x5B6, 0x8B6, 0xBB6, 0xEB6};
const uint16_t UNIT_ADDRESSES[] =         {0x2B7, 0x5B7, 0x8B7, 0xBB7, 0xEB6};

// Flow Units and their respective codes.
const char    *FLOW_UNIT[] = {"nl/min", "ul/min", "ml/min", "ul/sec", "ml/h"};
const uint16_t FLOW_UNIT_CODES[] = {2115, 2116, 2117, 2100, 2133};

uint16_t scale_factor;
const char *unit;

float calib; //calibration value of sensor
float total_volume = 0; //total volume run through the sensor
unsigned long start_time;
unsigned long last_read_time;

char TimeString[9];
char ServoString[3];


//Setup the LCD Shield
Adafruit_RGBLCDShield lcd = Adafruit_RGBLCDShield();
// These #defines make it easy to set the backlight color
#define RED 0x1
#define YELLOW 0x3
#define GREEN 0x2
#define TEAL 0x6
#define BLUE 0x4
#define VIOLET 0x5
#define WHITE 0x7


// Read one value function

float ReadOneSensirion(int SAddress) {
  int ret;
  uint16_t raw_sensor_value;
  float sensor_reading;
  
  // To perform a measurement, first send 0xF1 to switch to measurement mode,
  // then read 2 bytes + 1 CRC byte from the sensor.
  Wire.beginTransmission(SAddress);
  Wire.write(0xF1);
  ret = Wire.endTransmission();
  if (ret != 0) {
    Serial.println("Error during write measurement mode command");
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.setBacklight(RED);
    lcd.print("ERR: Measure Mode");

  } else {
    Wire.requestFrom(SAddress, 2);       // reading 2 bytes ignores the CRC byte
    if (Wire.available() < 2) {
      Serial.println("Error while reading flow measurement");

    } else {
      raw_sensor_value  = Wire.read() << 8; // read the MSB from the sensor
      raw_sensor_value |= Wire.read();      // read the LSB from the sensor
      sensor_reading = ((int16_t) raw_sensor_value) / ((float) scale_factor);
      
      Serial.print("raw value from sensor: ");
      Serial.print(raw_sensor_value);


    }
  }
  return sensor_reading;  
}

// Read a number of Measurements in a n approximate msec block
// can set msec to 0 to measure as quickly as possible
// running this function will take longer than msec
float ReadXinYTime(int numMeas, int msec, int SAddress){
  float avgValue = 0;
  for (int i=1; i <= numMeas; i++){
    avgValue += ReadOneSensirion(SAddress)/numMeas;
    delay(msec/numMeas);
  }
  return avgValue;
}

// Write out time in hh:mm:ss format to lcd
void HHMMSStoLCD(long msecs){
  int hh = msecs/3600000;
  int mm = (msecs % 3600000)/60000;
  int ss = ((msecs % 3600000) % 60000)/1000;

  sprintf_P(TimeString, PSTR("%d:%02d:%02d"), hh, mm, ss);

  lcd.print(TimeString);
  
}

void ServoPostoLCD(int pos){
  sprintf_P(ServoString, PSTR("%03d"), pos);
  lcd.print(ServoString);
}

// -----------------------------------------------------------------------------
// Arduino setup routine, just runs once:
// -----------------------------------------------------------------------------
void setup() {
  int ret;

  uint16_t user_reg;
  uint16_t scale_factor_address;

  uint16_t unit_code;

  byte crc1;
  byte crc2;

  // set up the LCD's number of columns and rows: 
  lcd.begin(16, 2);
  lcd.setBacklight(RED);
  lcd.print("LCD Initialized");
  delay(500);
  
  myservo.attach(9);  // attaches the servo on pin 9 to the servo object
  myservo.write(ZEROFLOW);
  delay(500);
  lcd.setCursor(0,1);
  lcd.print("Servo Init OK");
  delay(500);
  
  Serial.begin(9600); // initialize serial communication
  Wire.begin();       // join i2c bus (address optional for master)

  do {
    delay(1000); // Error handling for example: wait a second, then try again

    // Soft reset the sensor
    Wire.beginTransmission(ADDRESS);
    Wire.write(0xFE);
    ret = Wire.endTransmission();
    if (ret != 0) {
      Serial.println("Error while sending soft reset command, retrying...");
      continue;
    }
    delay(50); // wait long enough for reset

    // Read the user register to get the active configuration field
    Wire.beginTransmission(ADDRESS);
    Wire.write(0xE3);
    ret = Wire.endTransmission();
    if (ret != 0) {
      Serial.println("Error while setting register read mode");
      continue;
    }

    Wire.requestFrom(ADDRESS, 2);
    if (Wire.available() < 2) {
      Serial.println("Error while reading register settings");
      continue;
    }
    user_reg  = Wire.read() << 8;
    user_reg |= Wire.read();

    // The active configuration field is determined by bit <6:4>
    // of the User Register
    scale_factor_address = SCALE_FACTOR_ADDRESSES[(user_reg & 0x0070) >> 4];

    // Read scale factor and measurement unit
    Wire.beginTransmission(ADDRESS);
    Wire.write(0xFA); // Set EEPROM read mode
    // Write left aligned 12 bit EEPROM address
    Wire.write(scale_factor_address >> 4);
    Wire.write((scale_factor_address << 12) >> 8);
    ret = Wire.endTransmission();
    if (ret != 0) {
      Serial.println("Error during write EEPROM address");
      continue;
    }

    // Read the scale factor and the adjacent unit
    Wire.requestFrom(ADDRESS, 6);
    if (Wire.available() < 6) {
      Serial.println("Error while reading EEPROM");
      continue;
    }
    scale_factor = Wire.read() << 8;
    scale_factor|= Wire.read();
    crc1         = Wire.read();
    unit_code    = Wire.read() << 8;
    unit_code   |= Wire.read();
    crc2         = Wire.read();

    switch (unit_code) {
     case 2115:
       { unit = FLOW_UNIT[0]; }
       break;
     case 2116:
       { unit = FLOW_UNIT[1]; }
       break;
     case 2117:
       { unit = FLOW_UNIT[2]; }
       break;
     case 2100:
       { unit = FLOW_UNIT[3]; }
       break;
     case 2133:
       { unit = FLOW_UNIT[4]; }
       break;
     default:
       Serial.println("Error: No matching unit code");
       break;
   }
  } while (ret != 0);

  
  delay(50); // wait long enough for chip reset to complete
  lcd.setCursor(0,1);
  lcd.print("Sensirion Connect");
  lcd.setBacklight(GREEN);
  delay(500);
  lcd.clear();

  lcd.setCursor(0,0);
  lcd.print("Scale:");
  lcd.setCursor(7,0);
  lcd.print(scale_factor);
  lcd.setCursor(0,1);
  lcd.print("Unit:");
  lcd.setCursor(6,1);
  lcd.print(unit);

  delay(2000);
  lcd.clear();

  // Now for a calibration section?
  uint8_t buttons;
  lcd.setCursor(0,0);
  lcd.print("Press Any Button");
  lcd.setCursor(0,1);
  lcd.print("for Calibration");
  do {
    buttons = lcd.readButtons();
    delay(250);
  } while(!buttons);
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Calibrating");
  calib = ReadXinYTime(10,3000,ADDRESS);
  lcd.clear();
  lcd.print("Calibrated");
  lcd.setCursor(0,1);
  lcd.print(calib);
  lcd.setCursor(6,1);
  lcd.print(unit);
  delay(3000);
  lcd.clear(); 


  //Prep for running the loop
  start_time = millis();
  last_read_time = start_time;
  lcd.setBacklight(BLUE);
  lcd.setCursor(15,0);
  lcd.print("A");
}
// -----------------------------------------------------------------------------
// The Arduino loop routine runs over and over again forever:
// -----------------------------------------------------------------------------
void loop() {
  float inst_value;
  unsigned long elapsed_time;
  String volume;
  uint8_t buttons;
  
  //lcd.clear();
  inst_value = max((ReadXinYTime(5,0,ADDRESS)-calib),0);
  // all will be based on a ul/min flow
  elapsed_time = millis() - last_read_time;
  last_read_time = millis();
  total_volume += inst_value*elapsed_time/60000; //in ul
  lcd.setCursor(0,1);
  lcd.print(inst_value);
  lcd.setCursor(8,1);
 // sprintf_P(Volume, PSTR("%d:%02d:%02d"), hh, mm, ss);
  lcd.print(total_volume/1000);  
  lcd.setCursor(0,0);
  HHMMSStoLCD((millis() - start_time));

  //check for done
  if (inst_value < 150) {
    //no flow
    if (total_volume > 300000) {
      //probably done
      lcd.setBacklight(GREEN);
    } else {
      // not enough flow completed
      lcd.setBacklight(RED);
    }
  }  else {
    //flowing
    lcd.setBacklight(BLUE);
  }


  if (manualFlag == 0){
    //We are in automatic control mode
    int deviation = inst_value - setpoint;
    if (deviation > window){
      //too much flow, need to slow down
      pos += 1;
      pos = min(pos,180);  //make sure pos doesn't exceed 180      
      lcd.setCursor(12,0);
      ServoPostoLCD(pos);
      myservo.write(pos);
    
    } else if (deviation < -window){
      //too little flow, need to speed up
      pos -= 1;
      pos = max(pos,0);  //make sure pos doesn't fall below 0   
      lcd.setCursor(12,0);
      ServoPostoLCD(pos);     
      myservo.write(pos); 
    }
    
//    pos += round(deviation/150); //gives us a 250 ul/min flow rate buffer around
//    pos = max(pos,0); //make sure the pos never goes below zero
    
    //need to come up with a "DONE" or flow rate is below zero case


  }

  buttons = lcd.readButtons();
  if (buttons) {
      if (buttons & BUTTON_UP) {
        pos += 5;
        pos = min(pos, 180); //pos never gets above 180
        myservo.write(pos);
      }
      if (buttons & BUTTON_DOWN) {
        pos -= 5; 
        pos = min(pos,0); //pos never gets below 0
        myservo.write(pos);
      }
      if (buttons & BUTTON_LEFT) {
        pos += 1;
        myservo.write(pos);
      }
      if (buttons & BUTTON_RIGHT) {
        pos -= 1;
        myservo.write(pos);
      }

      lcd.setCursor(12,0);
      lcd.print(pos);
      if (buttons & BUTTON_SELECT) {
        if (manualFlag == 1){
            lcd.setBacklight(TEAL);
            manualFlag = 0;
            lcd.setCursor(15,0);
            lcd.print("A"); 
        } else {
          lcd.setBacklight(BLUE);
          manualFlag == 1;
          lcd.setCursor(15,0);
          lcd.print("M"); 
        }
      } 
  }

  //delay(1000); // milliseconds delay between reads (for demo purposes)
}


