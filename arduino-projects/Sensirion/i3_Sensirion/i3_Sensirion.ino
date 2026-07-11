
// Current BAUD is 115200


#include <Wire.h> // Arduino library for I2C

const int ADDRESS = 0x50; // Standard address for Liquid Flow Sensors
int COUNT=0;
const bool VERBOSE_OUTPUT = true; // set to false for less verbose output

// EEPROM Addresses for factor and unit of calibration fields 0,1,2,3,4.
const uint16_t SCALE_FACTOR_ADDRESSES[] = {0x2B6, 0x5B6, 0x8B6, 0xBB6, 0xEB6};
const uint16_t UNIT_ADDRESSES[] =         {0x2B7, 0x5B7, 0x8B7, 0xBB7, 0xEB6};

// Flow Units and their respective codes.
const char    *FLOW_UNIT[] = {"nl/min", "ul/min", "ml/min", "ul/sec", "ml/h"};
const uint16_t FLOW_UNIT_CODES[] = {2115, 2116, 2117, 2100, 2133};

const uint8_t MIN_BIT_RESOLUTION = 9;
const uint8_t MAX_BIT_RESOLUTION = 16;

uint16_t scale_factor;
const char *unit;

// -----------------------------------------------------------------------------
// Arduino setup routine, just runs once:
// -----------------------------------------------------------------------------
void setup() {
  int ret;

  uint16_t user_reg;
  uint16_t scale_factor_address;
  uint16_t raw_sensor_value;
  uint16_t adv_user_reg_original;
  uint16_t adv_user_reg_new;
  uint16_t resolution_mask;
  uint16_t unit_code;

  byte crc1;
  byte crc2;

  static unsigned int sensor_resolution = 12; //in bits
  // The resolution setting is controlled by bits 11:9 of the advanced user
  // register.
  // Possible settings for the sensor flow resolution are:
  //    000: 9 bit (flow);
  //    001: 10 bit (flow);
  //    010: 11 bit (flow);
  //    011: 12 bit (flow);
  //    100: 13 bit (flow);
  //    101: 14 bit (flow);
  //    110: 15 bit (flow);
  //    111: 16 bit (flow);

  
  Serial.begin(115200); // initialize serial communication
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
    scale_factor_address = SCALE_FACTOR_ADDRESSES[((user_reg & 0x0070) >> 4)];

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

    if (VERBOSE_OUTPUT) {
      Serial.println();
      Serial.println("-----------------------");
      Serial.print("Scale factor: ");
      Serial.println(scale_factor);
      Serial.print("Unit: ");
      Serial.print(unit);
      Serial.print(", code: ");
      Serial.println(unit_code);
      Serial.println("-----------------------");
      Serial.println();
    }
  // Switch resolution
 
  resolution_mask = 0xF1FF | ((sensor_resolution - 9) << 9);
  Wire.beginTransmission(ADDRESS);
  Wire.write(0xE5);
  ret = Wire.endTransmission();
  if (ret != 0) {
    Serial.println("Error during write register read mode");

  } else {
    // Read the content of the adv user register
    Wire.requestFrom(ADDRESS, 2);
    if (Wire.available() < 2) {
      Serial.println("Error during read register settings");

    } else {
      adv_user_reg_original  = Wire.read() << 8;
      adv_user_reg_original |= Wire.read();
      adv_user_reg_new = (adv_user_reg_original | 0x0E00) & resolution_mask;

      if (VERBOSE_OUTPUT) {
        // Display register values and settings
        Serial.println();
        Serial.println("----------------");
        Serial.print("New resolution setting:       ");
        Serial.println(sensor_resolution);
        Serial.print("Resolution bit setting (BIN): ");
        Serial.println(sensor_resolution - 9, BIN);
        Serial.print("Resolution mask:     ");
        Serial.println(resolution_mask, BIN);
        Serial.print("Adv. user reg read:   ");
        Serial.println(adv_user_reg_original, BIN);
        Serial.print("Adv. user reg write:  ");
        Serial.println(adv_user_reg_new, BIN);
        Serial.println("----------------");
      }

      // Apply resolution changes:
      // Change mode to write to adv. user register
      Wire.beginTransmission(ADDRESS);
      Wire.write(0xE4);                           // Send command
      Wire.write((byte)(adv_user_reg_new >> 8));      // Send MSB
      Wire.write((byte)(adv_user_reg_new & 0xFF));    // Send LSB
      ret = Wire.endTransmission();
      if (ret != 0) {
        Serial.println("Error during write register settings");
      }
    }
  }

    // Switch to measurement mode
    Wire.beginTransmission(ADDRESS);
    Wire.write(0xF1);
    ret = Wire.endTransmission();
    if (ret != 0) {
      Serial.println("Error during write measurement mode command");
    }
  } while (ret != 0);

Serial.println("Taking Measurements");
Serial.println("Time,SignedValue(ul/min)");
}


// -----------------------------------------------------------------------------
// The Arduino loop routine runs over and over again forever:
// -----------------------------------------------------------------------------
void loop() {
  int ret;
  uint16_t raw_sensor_value;
  int16_t signed_sensor_value;
  unsigned long now;

    Wire.requestFrom(ADDRESS, 2);       // reading 2 bytes ignores the CRC byte
    if (Wire.available() < 2) {
      Serial.println("Error while reading flow measurement");

    } else {
      raw_sensor_value  = Wire.read() << 8; // read the MSB from the sensor
      raw_sensor_value |= Wire.read();      // read the LSB from the sensor

      //Serial.print("Time: ");
      Serial.print(millis());
      Serial.print(",");
        
      //Serial.print(" raw: ");
      Serial.println((int16_t) raw_sensor_value);  // output is signed sensor value
    }
  

 // delay(1000); // milliseconds delay between reads (for demo purposes)
}

