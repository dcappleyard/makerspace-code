
#include "Arduino.h"
#include "uRTCLib.h"

// uRTCLib rtc;
uRTCLib rtc(0x68);

char daysOfTheWeek[7][12] = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};

int pin = 9;  //  PWM pin for minutes
int hourpin = 10; // PWM pin for hours
int minout = 0;
int hourout = 0;


void setDisplay(float minutes, float hours){
  //Minutes is 0-59 hours is 0-12
  if(minutes < 0 || minutes > 60){
    Serial.println("Error minutes out of range, Minutes: " + String(minutes));
    return;
  }
  if(hours < 0 || hours > 12){
    Serial.println("Error hour out of range, Hours: " + String(hours));
    hours = hours - 12;
    //return;
  }
  int minute_converted = ((minutes+0.0001)/60.0) * 255;
  int hour_converted = ((hours+0.0001)/12.0) * 255;
  analogWrite(pin, minute_converted);
  analogWrite(hourpin, hour_converted);

  Serial.print("minute_converted: ");
  Serial.print(minute_converted);
  Serial.print("   hour_converted: ");
  Serial.println(hour_converted);
}

void setup() {
 
 Serial.begin(9600);
 delay(3000); // wait for console opening

 URTCLIB_WIRE.begin();

 pinMode(pin, OUTPUT);

// Only use once, then disable
// rtc.set(0, 42, 16, 6, 2, 5, 15);
//  RTCLib::set(byte second, byte minute, byte hour (0-23:24-hr mode only), byte dayOfWeek (Sun = 1, Sat = 7), byte dayOfMonth (1-12), byte month, byte year)
//rtc.set(0, 20, 7, 6, 2, 2, 2024);

}

void loop() {
  rtc.refresh();

Serial.print(rtc.hour());
Serial.print(':');
Serial.print(rtc.minute());
Serial.println();

hourout = rtc.hour();
minout = rtc.minute();

setDisplay(minout, hourout);

delay(5000); 

}