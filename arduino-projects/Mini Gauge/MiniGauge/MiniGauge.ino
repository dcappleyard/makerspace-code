#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <OBD.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <Adafruit_STMPE610.h>


// For the Adafruit shield, these are the default.
#define TFT_DC 9
#define TFT_CS 10

// Use hardware SPI (on Uno, #13, #12, #11) and the above for CS/DC
Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC);

// This is calibration data for the raw touch data to the screen coordinates
#define TS_MINX 150
#define TS_MINY 130
#define TS_MAXX 3800
#define TS_MAXY 4000

// These are car constants
#define MAXRPM 10000
#define MAXSPEED 100

// The STMPE610 uses hardware SPI on the shield, and #8
#define STMPE_CS 8
Adafruit_STMPE610 ts = Adafruit_STMPE610(STMPE_CS);

//Define the PIDs that will be read in for each screen
static byte pidScreen1[]= {PID_RPM, PID_SPEED, PID_AMBIENT_TEMP, PID_INTAKE_TEMP, PID_COOLANT_TEMP, PID_ENGINE_OIL_TEMP};
static byte pidScreen2[]= {PID_FUEL_LEVEL, PID_ENGINE_FUEL_RATE, PID_FUEL_PRESSURE, PID_FUEL_RAIL_PRESSURE, PID_TIMING_ADVANCE, PID_ENGINE_LOAD, PID_ENGINE_REF_TORQUE};
//Define the ODB controller
COBD obd;

int numScreens = 3;
int screenIdx = 2;
int tsBuffer = 0;

bool debug = true;

void setup() {

 
  tft.begin();
  tft.fillScreen(ILI9341_BLACK);
  tft.setRotation(1); //usb jack in top left, landscape
  tft.setCursor(140,115);
  tft.setTextColor(ILI9341_RED, ILI9341_BLACK);
  tft.setTextSize(2);
  tft.print("Connecting...");
  obd.begin();
  // initiate OBD-II connection until success
  while (!obd.init());  
  tft.fillScreen(ILI9341_BLACK);
  tft.setCursor(140,115);
  tft.setTextColor(ILI9341_GREEN, ILI9341_BLACK);
  tft.setTextSize(2);
  tft.print("Connected!!");
  delay(1000);
  tft.fillScreen(ILI9341_BLACK);  
  drawScreen(screenIdx);
  
  ts.begin();


}


void loop(void) {
  // See if there's any touch data (hopefully?)
  if (!ts.touched()) {
    //my guess is this is where we do everything.  
   drawScreen(screenIdx);
    return;
  } else {
    // should this be an else?
    // Retrieve a point  
    TS_Point p = ts.getPoint();
    while (ts.bufferSize()){
      //empty the buffer
      p = ts.getPoint();
    }

    
    //debug
// 
//     tft.setCursor(50,150);
//     tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
//     String param = "X: ";
//     param = param + p.x + " Y: " + p.y + " buffer size: " + tsBuffer + "  ";
//     tft.print(param);
    //end debug 
    
    if (p.y < 1800 && screenIdx > 1){
      screenIdx--;
    } else if (p.y > 2000 && screenIdx < numScreens) {
      screenIdx++;
    }
    tft.fillScreen(ILI9341_BLACK);
    drawScreen(screenIdx);
    

    delay(250);
  }
  
}


void drawScreen(int scIdx) {
  int value;
 //blank string for making display numbers 
 String blank = "";

  switch(scIdx){
    case 1:
    //define screen 1
    if (!debug){
      obd.read(PID_SPEED,value);
      obd.read(PID_RPM, value);
      obd.read(PID_AMBIENT_TEMP, value);
      obd.read(PID_INTAKE_TEMP, value);
      obd.read(PID_COOLANT_TEMP, value);
      obd.read(PID_ENGINE_OIL_TEMP, value);
    }else{
     value=random(0,700);
    } 
      drawTitledGauge(0, 0, 80, 240, 4, value/MAXSPEED*100,55/MAXSPEED*100, 70/MAXSPEED*100, "Speed", blank + value);
      drawTitledGauge(80, 0, 80, 240, 4, value/MAXRPM * 100,50, 25, "RPM", blank + value);
      drawTitledGauge(160, 0, 80, 240, 4, 25,50, 25, "Turbo RPM", "N/A");
      drawSmallValueRect(240,0,"Ambient", blank + value + (char)247 + "C");
      drawSmallValueRect(240,48,"Intake", blank + value + (char)247 + "C" );
      drawSmallValueRect(240,96,"Coolant",blank + value + (char)247 + "C");
      drawSmallValueRect(240,144,"Oil",blank + value + (char)247 + "C");
      drawSmallValueRect(240,192,"Turbo",blank + "N/A");
    break;
    case 2:

    break;
    case 3:
     //define screen 3
     if (!debug){
      obd.read(PID_FUEL_LEVEL, value);
      obd.read(PID_ENGINE_FUEL_RATE, value); 
      obd.read(PID_FUEL_PRESSURE, value);
      obd.read(PID_FUEL_RAIL_PRESSURE, value);     
      obd.read(PID_TIMING_ADVANCE, value);     
      obd.read(PID_ENGINE_LOAD, value);     
      obd.read(PID_ENGINE_REF_TORQUE, value);
     }else{
       value=random(0,700);
     }

      drawMediumValueRect(0,0,"Fuel Level", blank + value + "%" );
      drawMediumValueRect(0,60,"Fuel Rate", blank + value + "L/h");
      drawMediumValueRect(0,120,"Fuel Pressure", blank + value + "kPa");
      drawMediumValueRect(0,180,"Fuel Rail Press.", blank + value + "kPa");
      drawMediumValueRect(160,0,"Timing Advance", blank + value + (char)247 );
      drawMediumValueRect(160,60,"Engine Load", blank + value + "?");
      drawMediumValueRect(160,120,"Driver Demand Torque",blank + 50 + "Nm");
      drawMediumValueRect(160,180,"Engine Torque", blank + value + "Nm");      
    break;
    case 4:
     //define screen 4
    break;

  }
}

void updateScreen(int scIdx) {
  int value;
 //blank string for making display numbers 
 String blank = "";

  switch(scIdx){
    case 1:
    //define screen 1
    if (!debug){
      obd.read(PID_SPEED,value);
      obd.read(PID_RPM, value);
      obd.read(PID_AMBIENT_TEMP, value);
      obd.read(PID_INTAKE_TEMP, value);
      obd.read(PID_COOLANT_TEMP, value);
      obd.read(PID_ENGINE_OIL_TEMP, value);
    }else{
     value=random(0,100);
    } 
      
      updateTitledGauge(0, 0, 80, 240, 4, value/MAXSPEED*100,55/MAXSPEED*100, 70/MAXSPEED*100, "Speed", blank + value);    
      updateTitledGauge(80, 0, 80, 240, 4, value/MAXSPEED* 100,50, 25, "RPM", blank + value);
      updateTitledGauge(160, 0, 80, 240, 4, 25,50, 25, "Turbo RPM", "N/A");
      updateSmallValueRect(240,0, blank + value + (char)247 + "C");  //Ambient
      updateSmallValueRect(240,48, blank + value + (char)247 + "C" );  //"Intake"
      updateSmallValueRect(240,96,blank + value + (char)247 + "C"); //"Coolant"
      updateSmallValueRect(240,144,blank + value + (char)247 + "C"); //"Oil"
      updateSmallValueRect(240,192,blank + "N/A"); //"Turbo"
    break;
    case 2:
    break;
    case 3:
     //define screen 3
     if (!debug){
      obd.read(PID_FUEL_LEVEL, value);
      obd.read(PID_ENGINE_FUEL_RATE, value); 
      obd.read(PID_FUEL_PRESSURE, value);
      obd.read(PID_FUEL_RAIL_PRESSURE, value);     
      obd.read(PID_TIMING_ADVANCE, value);     
      obd.read(PID_ENGINE_LOAD, value);     
      obd.read(PID_ENGINE_REF_TORQUE, value);
     }else{
       value=random(0,700);
     }
      
      updateMediumValueRect(0,0, blank + value + "%" );  //"Fuel Level"
      updateMediumValueRect(0,60, blank + value + "L/h"); //"Fuel Rate"
      updateMediumValueRect(0,120, blank + value + "kPa"); //"Fuel Pressure"
      updateMediumValueRect(0,180, blank + value + "kPa"); //"Fuel Rail Press."
      updateMediumValueRect(160,0, blank + value + (char)247 ); //"Timing Advance"
      updateMediumValueRect(160,60, blank + value + "?"); //"Engine Load"
      updateMediumValueRect(160,120,blank + 50 + "Nm"); //"Driver Demand Torque"
      updateMediumValueRect(160,180, blank + value + "Nm"); //"Engine Torque"  
      
    break;
    case 4:
     //define screen 4

    break;

  }
}



void drawTitledGauge(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, int radius, uint16_t vp, uint16_t gp, uint16_t yp, String title, String dispString){
  //draw the outline
  tft.drawRoundRect(x0,y0,w,h,radius,ILI9341_WHITE);
  
  //draw the title
  tft.setTextSize(1);
  tft.setCursor(x0+radius,y0+3);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.print(title);
  
  //draw the value
  tft.setCursor((int)(x0 + w/2 - dispString.length()*10/2), (int)(y0 + h - 3 - 16));
  tft.setTextSize(2);
  tft.print(dispString);
  
  //draw the guage
  explicitRectGauge(x0+w/4,y0+3+8+10,w/2,h-3-16-10-21,vp,gp,yp);
}


void updateTitledGauge(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, int radius, uint16_t vp, uint16_t gp, uint16_t yp, String title, String dispString){
  //draw the outline
  tft.drawRoundRect(x0,y0,w,h,radius,ILI9341_WHITE);
  
  //draw the title
  tft.setTextSize(1);
  tft.setCursor(x0+radius,y0+3);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.print(title);
  
  //draw the value
  tft.setCursor((int)(x0 + w/2 - dispString.length()*10/2), (int)(y0 + h - 3 - 16));
  tft.setTextSize(2);
  tft.print(dispString);
  
  //draw the guage
  explicitRectGauge(x0+w/4,y0+3+8+10,w/2,h-3-16-10-21,vp,gp,yp);
}


void updateRoundRectValue(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, uint16_t radius, String dispString){

  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);

  
  //put in the value
  tft.setCursor((int)(x0 + w/2 - dispString.length()*10/2), (int)(y0 + (h-radius-8)/2 + radius));
  tft.setTextSize(2);
  tft.print(dispString);
  


}

void drawRoundRectValue(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, uint16_t radius, String title, String dispString){
  //draw the outline
  tft.drawRoundRect(x0,y0,w,h,radius,ILI9341_WHITE);
  
  //put in the title
  tft.setTextSize(1);
  tft.setCursor(x0+radius,y0+3);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.print(title);
  
  //put in the value
  tft.setCursor((int)(x0 + w/2 - dispString.length()*10/2), (int)(y0 + (h-radius-8)/2 + radius));
  tft.setTextSize(2);
  tft.print(dispString);
  


}

void updateSmallValueRect(uint16_t x0, uint16_t y0, String dispString){
  //makes a small Value in a rectangle that is 1/5 of the screen tall, 1/4 wide
  updateRoundRectValue(x0,y0,80,48,4,dispString);
}

void updateMediumValueRect(uint16_t x0, uint16_t y0, String dispString){
  //makes a medium Value rectangle that is 1/4 of the screen tall, 1/2 wide
  updateRoundRectValue(x0,y0,160,60,4,dispString);
}

void drawSmallValueRect(uint16_t x0, uint16_t y0, String title, String dispString){
  //makes a small Value in a rectangle that is 1/5 of the screen tall, 1/4 wide
  drawRoundRectValue(x0,y0,80,48,4,title,dispString);
}

void drawMediumValueRect(uint16_t x0, uint16_t y0, String title, String dispString){
  //makes a medium Value rectangle that is 1/4 of the screen tall, 1/2 wide
  drawRoundRectValue(x0,y0,160,60,4,title,dispString);
}

void explicitRectGauge(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, uint16_t vp, uint16_t gp, uint16_t yp) {
 // x0 top left x position
 // y0 top left y position
 // w width
 // h height
 // vp value percentage displayed
 // gp green percentage of the bar
 // yp yellow percentage of the bar
 // rp red percentage of the bar
 
 int rp = 0; //default red
 
 if (gp + yp > 100) {//Double check that inputs were reasonable
   gp = 50;
   yp = 25;
 }
 
 rp = 100 - gp - yp;  //red percentage is what ever is left 
 
 if (w > 320) { //check width
  w = 320;
 }
 if (h > 240) { // check height
  h = 240;
 }
 
 int gtl = y0+h*(yp+rp)/100; //green top left
 int ytl = y0+h*(rp)/100;  //yellow top left
 
// tft.setCursor(50,0);
// tft.setTextSize(1);
// tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
// String param = "vp: ";
// param = param + vp + " rp: " + rp + " gtl: " + gtl + " ytl: " + ytl;
// tft.print(param);
 
 // clear with a black background rectangle
 tft.fillRect(x0,y0,w,h,ILI9341_BLACK);
 
 if (vp <= gp) { // will have to draw a short green
   tft.fillRect(x0,gtl+(h*(gp-vp)/100),w,h*vp/100,ILI9341_GREEN);
   return;
   //break / return
 }else{
   // draw full green
   tft.fillRect(x0,gtl,w,h*gp/100,ILI9341_GREEN);
   
   if (vp <= (gp + yp)) { // will have to draw a short yellow
     tft.fillRect(x0,ytl+(h*(gp+yp-vp)/100),w,h*(vp-gp)/100,ILI9341_YELLOW);
     return;
  
   }else{
     // draw full yellow
     tft.fillRect(x0,ytl,w,h*yp/100,ILI9341_YELLOW);
     
     if (vp < (gp + yp + rp)) { // will have to draw a short red
       tft.fillRect(x0,y0+(h*(gp+yp+rp-vp)/100),w,h*(vp-gp-yp)/100,ILI9341_RED);
       return;
     }else{
       // draw full red
       tft.fillRect(x0,y0,w,h*rp/100,ILI9341_RED);
     }
   }
 }
}
