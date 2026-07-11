/*
 * sensirion.cpp - Sensirion Commands
 * Created by DCAppleyard 2018-12-03
 * Revision #1
 */

//	The #include of Arduino.h gives this library access to the standard
//  functions
#include "Arduino.h"

//	This will include the Header File so that the Source File has access
//	to the function definitions in the Sensirion library.
#include "Sensirion.h" 

#include "Wire.h"

//	This is where the constructor Source Code appears. The '::' indicates that
//	it is part of the Sensirion class and should be used for all constructors
//	and functions that are part of a class.
Sensirion::Sensirion(int address){
	_address = address; // Set the I2C address of the sensor
	_calibrationValue = 0; // Set the calibration value to 0

}

//	For the 'on', 'off' and 'flash' functions, their function return type (void) is
//	specified before the class-function link. They also use the private variables
//	saved in the constructor code.

bool Sensirion::connect(){
	int ret;
	
 	Wire.begin();   //Start the I2C connection
	delay(250);		//Wait to get things going    
    // Soft reset the sensor
    Wire.beginTransmission(_address);
    Wire.write(0xFE);
    ret = Wire.endTransmission();
    if (ret != 0) {
      return false;
    }
    return true;
}

int Sensirion::getResolution(){
	unsigned long long adv_user_reg_new;
	unsigned long long adv_user_reg_original;
	unsigned long long resolution_mask;
	int ret;
	
	// read resolution
	
	// Need a brief delay if this follows another command
	delay(250);
	//  resolution_mask = 0xF1FF | ((sensor_resolution - 9) << 9);
	Wire.beginTransmission(_address);
	Wire.write(0xE5);
	ret = Wire.endTransmission();
	if (ret != 0) {
		//Serial.println("Error during write register read mode");
		return 10; // right now, 9 represents an error

	} else {
		// Read the content of the adv user register
		Wire.requestFrom(_address, 2);
		if (Wire.available() < 2) {
		  //Serial.println("Error during read register settings");
		  return 11;

		} else {
		  adv_user_reg_original  = Wire.read() << 8;
		  adv_user_reg_original |= Wire.read();
		  //need to do something here to adv_user_reg_original to get last 9 bits
		  resolution_mask = (0x0E00 & adv_user_reg_original)>>9;
		  // now need to add 9 to bring it back
		  return resolution_mask + 9;
		  //adv_user_reg_new = (adv_user_reg_original | 0x0E00) & resolution_mask;
		}
	}
}

bool Sensirion::setResolution(int sensor_resolution){
	unsigned long long adv_user_reg_new;
	unsigned long long adv_user_reg_original;
	unsigned long long resolution_mask;
	int ret;

	// Need a brief delay if this follows another command
	delay(250);
	
	// static unsigned int sensor_resolution = 12; //in bits
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
	// Set the Sensirion resolution 
	
	//error check the resolution
	if (sensor_resolution > 16) {
		sensor_resolution = 16;
	}
	if (sensor_resolution < 9) {
		sensor_resolution = 9;
	}
	
	resolution_mask = 0xF1FF | ((sensor_resolution - 9) << 9);
	Wire.beginTransmission(_address);
	Wire.write(0xE5);
	ret = Wire.endTransmission();
	if (ret != 0) {
		//Serial.println("Error during write register read mode");
		return false;

	} else {
		// Read the content of the adv user register
		Wire.requestFrom(_address, 2);
		if (Wire.available() < 2) {
			//Serial.println("Error during read register settings");
			return false;

		} else {
			adv_user_reg_original  = Wire.read() << 8;
			adv_user_reg_original |= Wire.read();
			adv_user_reg_new = (adv_user_reg_original | 0x0E00) & resolution_mask;
		// 
		//       if (VERBOSE_OUTPUT) {
		//         // Display register values and settings
		//         Serial.println();
		//         Serial.println("----------------");
		//         Serial.print("New resolution setting:       ");
		//         Serial.println(sensor_resolution);
		//         Serial.print("Resolution bit setting (BIN): ");
		//         Serial.println(sensor_resolution - 9, BIN);
		//         Serial.print("Resolution mask:     ");
		//         Serial.println(resolution_mask, BIN);
		//         Serial.print("Adv. user reg read:   ");
		//         Serial.println(adv_user_reg_original, BIN);
		//         Serial.print("Adv. user reg write:  ");
		//         Serial.println(adv_user_reg_new, BIN);
		//         Serial.println("----------------");
		//       }

			// Apply resolution changes:
			// Change mode to write to adv. user register
			Wire.beginTransmission(_address);
			Wire.write(0xE4);                           // Send command
			Wire.write((byte)(adv_user_reg_new >> 8));      // Send MSB
			Wire.write((byte)(adv_user_reg_new & 0xFF));    // Send LSB
			ret = Wire.endTransmission();
			if (ret != 0) {
				//Serial.println("Error during write register settings");
				return false;
			} else {
				//All went well and write was successful
				return true;
			}
		}
	}
}

bool Sensirion::startMeasurementMode(){
	int ret;
	// Switch to measurement mode
	Wire.beginTransmission(_address);
	Wire.write(0xF1);
	ret = Wire.endTransmission();
	if (ret != 0) {
		//Serial.println("Error during write measurement mode command");
		return false;
	} else {
		//successful.. I assume
		return true;
	}
}

long Sensirion::getRawSensorValue(){

	int ret;
	unsigned long long raw_sensor_value;
	long long signed_sensor_value;

	Wire.requestFrom(_address, 2);       // reading 2 bytes ignores the CRC byte
	if (Wire.available() < 2) {
		//Serial.println("Error while reading flow measurement");
		return 0;  //this isn't the right way to sendthe error
	} else {
		raw_sensor_value  = Wire.read() << 8; // read the MSB from the sensor
		raw_sensor_value |= Wire.read();      // read the LSB from the sensor
		signed_sensor_value = (long long) raw_sensor_value;
		return signed_sensor_value;
	}
}

long Sensirion::getSensorValue(){
	// return a calibrated sensor value
	return _calibrationValue + getRawSensorValue();
}


long Sensirion::getCalibrationValue(){
	return _calibrationValue;
}

bool Sensirion::setCalibrationValue(long calibValue){
	_calibrationValue = calibValue;
	return true;
}