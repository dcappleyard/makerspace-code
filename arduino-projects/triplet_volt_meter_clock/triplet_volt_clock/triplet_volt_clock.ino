/*
 * Volt meter based clock
 * Designed around a Triplett PL 630
 * 
 * Inspired by https://hackaday.io/project/194872-analog-meter-arduino-clock
 * 
 * Minutes will be displayed on the voltmeter
 * Hours will be displayed in binary using 4 LEDs
 * 
 * SPST will be used to toggle DST
 * 
 * RTC DS3231 will be used for time keeping
 */

#include "Arduino.h"
#include "uRTCLib.h"

// uRTCLib rtc;
uRTCLib rtc(0x68);

char daysOfTheWeek[7][12] = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};

int PWM_PIN = 9;  //  PWM pin for minutes
int hourpin = 10; // PWM pin for hours
int minout = 0;
int hourout = 0;

const byte SWITCH_PIN = 13;  // Switch pin, must be pulled low with a 10K + resistor to GND

const float VOLTAGE_RANGE = 2.5;  // Voltage range of the multimeter (2.5V for Triplet)

int PIN_BIN_0 = 2;  //Binary LED LSB 
int PIN_BIN_1 = 3;  //Binary LED 
int PIN_BIN_2 = 4;  //Binary LED 
int PIN_BIN_3 = 5;  //Binary LED 
int PIN_BIN_4 = 6;  //Binary LED MSB

void setup_binary_LEDs(){
  /* Setup the outputs for the binary lights
   *  Will set the light state low
   *  
   */

   pinMode(PIN_BIN_0, OUTPUT);
   digitalWrite(PIN_BIN_0, LOW);
   pinMode(PIN_BIN_1, OUTPUT);
   digitalWrite(PIN_BIN_1, LOW);
   pinMode(PIN_BIN_2, OUTPUT);
   digitalWrite(PIN_BIN_2, LOW);
   pinMode(PIN_BIN_3, OUTPUT);
   digitalWrite(PIN_BIN_3, LOW);
   pinMode(PIN_BIN_4, OUTPUT);
   digitalWrite(PIN_BIN_4, LOW);
}

void setRTC() {
  /* 
   *  RTCLib::set(
   *  byte second, 
   *  byte minute, 
   *  byte hour (0-23:24-hr mode only), 
   *  byte dayOfWeek (Sun = 1, Sat = 7), 
   *  byte dayOfMonth (1-12), 
   *  byte month, 
   *  byte year)
   */
  rtc.set(0, 10, 12, 7, 23, 3, 2024);
}


void setMinutes(float minutes){
  /* 
   *  Set the minutes on the volt meter
   *  Conveniently, the Triplett has a 2.5V full scale option
   *  So you don't have to got rogue and replace a resistor.  Win!
   *  
   *  Analog output on the Uno is "faked" via PWM on digital IO pins
   *  at something like 500Hz
   *  Per Arduino reference for analogWrite()
   *  value: the duty cycle: between 0 (always off) and 255 (always on). Allowed data types: int.
   */
   
  //Error check - Minutes is 0-59 hours is 0-12
  if(minutes < 0 || minutes > 60){
    Serial.println("Error minutes out of range, Minutes: " + String(minutes));
    return;
  }
  
  int minute_converted = ((minutes+0.0001)/60.0) * 255 * VOLTAGE_RANGE/5;  //Scale to voltage range of meter
  analogWrite(PWM_PIN, minute_converted); //note, some multimeters may read this oddly depending on freqency.

  Serial.print("minute_converted: ");
  Serial.println(minute_converted);
  
}

void setHours(int hours){
  /* 
   *  The hour value of the clock will be done via 4 LEDs as binary
   *  Left to right: MSB to LSB
   *  
   *  A SPST swtich will be used to add an hour during daylight savings time
   *  
   *  
   */
   byte bit_hour = (byte)hours; //B10101; //(int)hours;
   byte mask = B00100;
   
   // add an hour if it is daylight savings
   if (digitalRead(SWITCH_PIN)==HIGH){
    hours = hours + 1;
    if (hours > 23) {
      hours = 0;
    }
    bit_hour = (byte)hours;
   }
 
   mask = B00001;
   if (mask & bit_hour){
    digitalWrite(PIN_BIN_0,HIGH);
   }
   else{
    digitalWrite(PIN_BIN_0,LOW);
   }
   mask = B00010;
   if (mask & bit_hour){
    digitalWrite(PIN_BIN_1,HIGH);
   }
   else{
    digitalWrite(PIN_BIN_1,LOW);
   }
   mask = B00100;
   if (mask & bit_hour){
    digitalWrite(PIN_BIN_2,HIGH);
   }
   else{
    digitalWrite(PIN_BIN_2,LOW);
   }
   mask = B01000;
   if (mask & bit_hour){
    digitalWrite(PIN_BIN_3,HIGH);
   }
   else{
    digitalWrite(PIN_BIN_3,LOW);
   }
   mask = B10000;
   if (mask & bit_hour){
    digitalWrite(PIN_BIN_4,HIGH);
   }
   else{
    digitalWrite(PIN_BIN_4,LOW);
   }
   
   
}
//void setDisplay(float minutes, float hours){
//  //Minutes is 0-59 hours is 0-12
//  if(minutes < 0 || minutes > 60){
//    Serial.println("Error minutes out of range, Minutes: " + String(minutes));
//    return;
//  }
//  if(hours < 0 || hours > 12){
//    Serial.println("Error hour out of range, Hours: " + String(hours));
//    hours = hours - 12;
//    //return;
//  }
//  int minute_converted = ((minutes+0.0001)/60.0) * 255;
//  int hour_converted = ((hours+0.0001)/12.0) * 255;
//  analogWrite(pin, minute_converted);
//  analogWrite(hourpin, hour_converted);
//
//  Serial.print("minute_converted: ");
//  Serial.print(minute_converted);
//  Serial.print("   hour_converted: ");
//  Serial.println(hour_converted);
//}

void setup() {
 
 Serial.begin(9600);
 delay(3000); // wait for console opening

 URTCLIB_WIRE.begin();

 // Setup the PWM_PIN
 pinMode(PWM_PIN, OUTPUT);

 // Setup the Switch Pin
 pinMode(SWITCH_PIN, INPUT);

 // Setup the LEDS
 setup_binary_LEDs();

 // Setup the RTC - only use this line initially, then comment out (unless need to reset clock)
 // setRTC();
 // Serial.println("Setup completed successfully");
 
}

void loop() {
  rtc.refresh();
  
  Serial.print(rtc.hour());
  Serial.print(':');
  Serial.print(rtc.minute());
  Serial.println();
  
  hourout = rtc.hour();
  minout = rtc.minute();
  
  setMinutes(minout);
  setHours(hourout);
  delay(4000); 

}
