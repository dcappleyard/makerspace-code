

//	The #ifndef statement checks to see if the myFirstLibrary.h
//	file isn't already defined. This is to stop double declarations
//	of any identifiers within the library. It is paired with a
//	#endif at the bottom of the header and this setup is known as 
//	an 'Include Guard'. 
#ifndef Sensirion_h

//	The #define statement defines this file as the myFirstLibrary
//	Header File so that it can be included within the source file.                                           
#define Sensirion_h

//	The #include of Arduino.h gives this library access to the standard
//	Arduino types and constants (HIGH, digitalWrite, etc.). It's 
//	unneccesary for sketches but required for libraries as they're not
//	.ino (Arduino) files.
#include "Arduino.h"

//	The class is where all the functions for the library are stored,
//	along with all the variables required to make it operate
class Sensirion{

	//	'public:' and 'private:' refer to the security of the functions
	//	and variables listed in that set. Contents that are public can be 
	//	accessed from a sketch for use, however private contents can only be
	//	accessed from within the class itself.
	public:
	
		//	Constructor
		Sensirion(int address);
		
		//	Functions
		bool connect();    
		
		int getResolution();
		
		bool setResolution(int sensirion_resolution);     
		
		bool startMeasurementMode();     
		
		long getRawSensorValue();
		
		long getSensorValue();
		
		long getCalibrationValue();
		
		bool setCalibrationValue(long calibValue);


	private:                  
		
		//	When dealing with private variables, it is common convention to place
		//	an underscore before the variable name to let a user know the variable
		//	is private.		
		int _address;  //Address of the Sensirion
		long _calibrationValue;  //Calibration Value for the Sensirion
};

//	The end wrapping of the #ifndef Include Guard
#endif