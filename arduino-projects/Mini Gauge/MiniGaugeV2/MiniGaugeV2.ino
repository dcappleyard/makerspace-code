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

// Shift LED locations
#define SHIFTNOWPIN 31
#define OVERSHIFTPIN 30

// Pseudo PIDs
#define PPID_GEAR -100

// The STMPE610 uses hardware SPI on the shield, and #8
#define STMPE_CS 8
Adafruit_STMPE610 ts = Adafruit_STMPE610(STMPE_CS);

//Define the ODB controller
COBD obd;

int numScreens = 4;
int screenIdx = 4;
int touchIdx = 0;
int updateCnt = 0;

bool debug = false;

void setup() {

  // turn off shift LEDs
  pinMode(SHIFTNOWPIN, OUTPUT);
  pinMode(OVERSHIFTPIN, OUTPUT);
  updateShiftLEDs(0);
  
  //start the screen
  tft.begin();
  tft.fillScreen(ILI9341_BLACK);
  tft.setRotation(2); //usb jack in bottom right, portrait
  
  //begin connection to the ODB
  tft.setCursor(25,115);
  tft.setTextColor(ILI9341_RED, ILI9341_BLACK);
  tft.setTextSize(2);
  tft.print("Connecting...");
  if (!debug) {
    obd.begin();
    // initiate OBD-II connection until success
    while (!obd.init());
  }  
  tft.fillScreen(ILI9341_BLACK);
  tft.setCursor(25,115);
  tft.setTextColor(ILI9341_GREEN, ILI9341_BLACK);
  tft.setTextSize(2);
  tft.print("Connected!!");
  delay(1000);
  
  //draw the screen
  drawTabs(screenIdx);  
  drawScreen(screenIdx);
  
  //start touch screen
  ts.begin();


}


void loop(void) {
  // See if there's any touch data (hopefully?)
  if (ts.touched()) {
      
    // Retrieve a point  
    TS_Point p = ts.getPoint();
    while (ts.bufferSize() !=0){
      //empty the buffer
      p = ts.getPoint();
      if (debug){
//         tft.setCursor(50,150);
//         tft.setTextSize(1);
//         tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
//         String param = "X: ";
//         param = param + p.x + " Y: " + p.y + " buffer size: " + ts.bufferSize() + "  tIDX: " + touchIdx;
//         tft.print(param);
      }
    }
    
    //because of oddness, we need to check if the screen has been touched right before
    if (touchIdx == 0) {
      touchIdx = 1;
      delay(150);
    } else {
    
      //swap screen idx.  power cable corner is 0, 0, ish.. x & y in portrait
      
      if (p.y < 1800 && p.x < 1800){
        screenIdx = 1; //lower left
      }else if(p.y > 1800 && p.x < 1800){
        screenIdx = 4; //lower right
      }else if(p.y < 1800 && p.x > 1800){
        screenIdx = 2; // upper left
      }else{
        screenIdx = 3; // upper right
      }
  
      drawTabs(screenIdx); 
      drawScreen(screenIdx);
      updateShiftLEDs(1);
      delay(100);
  
    //reset the touchIdx
      touchIdx = 0;
    }
  } else {
   // No touch!  Lets do otherwise  
   updateScreen(screenIdx);
    return;
 
  }
  
}

void drawScreen(int scIdx) {
  int value;
  int valueRPM, valueSpeed, valueCoolant, valueEngine, valueAmbient, valueIntake, valueBarometric, valueIntakeMAP;
  int valueFuelLevel, valueFuelRate, valueFuelPressure, valueRailPressure, valueTimingAdvance, valueEngineLoad;
  int valueMAFFlow;

 
  
 //blank string for making display numbers 
 String blank = "";

  switch(scIdx){
    case 1: //FUEL SYSTEM
    if (!debug){
      obd.read(PID_FUEL_LEVEL, valueFuelLevel);       // works!
      obd.read(PID_BAROMETRIC, valueBarometric);
      obd.read(PID_INTAKE_MAP, valueIntakeMAP);
//      obd.read(PID_ENGINE_FUEL_RATE, valueFuelRate);   //not working on mini
//      obd.read(PID_FUEL_PRESSURE, valueFuelPressure);    // may work, not interesting 
      obd.read(PID_TIMING_ADVANCE, valueTimingAdvance);  //works     
     }else{
       valueFuelLevel=random(0,100);  //Definitely works
       valueBarometric=random(0,255);
       valueIntakeMAP=random(0,255);
//       valueFuelRate=random(0,100);  // not working on Mini.. 
//       valueFuelPressure=random(0,60);
       valueTimingAdvance=random(0,360);  //definitely works
      // valueEngineLoad=random(0,200);
     }
    drawQuarterRect(0, 40, "Level", valueFuelLevel, PID_FUEL_LEVEL, 95);
    drawQuarterRect(120, 40, "Intake", valueIntakeMAP, PID_INTAKE_MAP, 150);
//    drawQuarterRect(120, 40, "Pressure", valueFuelPressure, PID_FUEL_PRESSURE, 1500);
    
    drawQuarterRect(0, 160, "Bar. P", valueBarometric, PID_BAROMETRIC, 140);
 //   drawQuarterRect(0, 160, "Rate", valueFuelRate, PID_ENGINE_FUEL_RATE, 80);
    drawQuarterRect(120, 160, "Timing", valueTimingAdvance, PID_TIMING_ADVANCE, 200);        
      
    

    break;
    case 2:
    //TEMPS
    if (!debug){
      obd.read(PID_AMBIENT_TEMP, valueAmbient);
      obd.read(PID_INTAKE_TEMP, valueIntake);
      obd.read(PID_COOLANT_TEMP, valueCoolant);
      obd.read(PID_MAF_FLOW, valueMAFFlow);
      //obd.read(PID_ENGINE_OIL_TEMP, valueEngine);  //not working on Mini, consistently
    }else{
     valueCoolant=random(0,60);
     valueAmbient=random(0,60);
     valueIntake=random(0,200);
     valueMAFFlow=random(0,655);
     //valueEngine=random(0,200);
    } 
    
//    drawQuarterRect(0, 40, "Oil", valueEngine, PID_ENGINE_OIL_TEMP, 100);
    drawQuarterRect(0, 40, "MAF Flow", valueMAFFlow, PID_MAF_FLOW, 400);
    
    drawQuarterRect(120, 40, "Coolant", valueCoolant, PID_COOLANT_TEMP, 120);

    drawQuarterRect(0, 160, "Intake", valueIntake, PID_INTAKE_TEMP, 40);
    drawQuarterRect(120, 160, "Ambient", valueAmbient, PID_AMBIENT_TEMP, 30);    
    
    break;
    case 3:
     // DIAGNOSTICS
    tft.setCursor(25,115);
    tft.setTextColor(ILI9341_RED, ILI9341_BLACK);
    tft.setTextSize(2);
    tft.print("Not Yet Available :(");
     
    break;
     
    case 4:
     //DRIVE
    if (!debug){
      obd.read(PID_SPEED,valueSpeed);
      obd.read(PID_RPM, valueRPM);
      updateShiftLEDs(valueRPM);

    }else{
     valueRPM=random(0,14000);
     valueSpeed=random(0,100);

    } 
    
    drawQuarterRect(0, 40, "Speed", valueSpeed, PID_SPEED, 105);;
    drawQuarterRect(120, 40, "RPM", valueRPM, PID_RPM, 8000);
    
    drawQuarterRect(120, 160, "Gear", Calculate_Gear(valueRPM, valueSpeed), PPID_GEAR, 7);
//    drawQuarterRect(0, 160, "Intake", valueIntake, PID_INTAKE_TEMP, 80);
//    drawQuarterRect(120, 160, "Ambient", valueAmbient, PID_AMBIENT_TEMP, 100);  
    
    break;

  }
}

void updateScreen(int scIdx) {
  int value;
  int valueRPM, valueSpeed, valueCoolant, valueEngine, valueAmbient, valueIntake, valueBarometric, valueIntakeMAP;
  int valueFuelLevel, valueFuelRate, valueFuelPressure, valueRailPressure, valueTimingAdvance, valueEngineLoad;
  int valueMAFFlow;
  
  
 //blank string for making display numbers 
 String blank = "";

  switch(scIdx){
    case 1: //FUEL SYSTEM
    if (!debug){
      obd.read(PID_FUEL_LEVEL, valueFuelLevel);
      obd.read(PID_BAROMETRIC, valueBarometric);
      obd.read(PID_INTAKE_MAP, valueIntakeMAP);
     // obd.read(PID_ENGINE_FUEL_RATE, valueFuelRate);   //not exceptionally useful on Mini
//      obd.read(PID_FUEL_PRESSURE, valueFuelPressure);     
      obd.read(PID_TIMING_ADVANCE, valueTimingAdvance);       
     }else{
       valueFuelLevel=random(0,100);
       valueBarometric=random(0,255);
       valueIntakeMAP=random(0,255);
//       valueFuelRate=random(0,100);
//       valueFuelPressure=random(0,60);
       valueTimingAdvance=random(0,360);
     }
    updateQuarterRect(0, 40, "Level", valueFuelLevel, PID_FUEL_LEVEL, 95);
    updateQuarterRect(120, 40, "Intake", valueIntakeMAP, PID_INTAKE_MAP, 150);
//    updateQuarterRect(120, 40, "Pressure", valueFuelPressure, PID_FUEL_PRESSURE, 1500);

    updateQuarterRect(0, 160, "Bar. P", valueBarometric, PID_BAROMETRIC, 140);     
//    updateQuarterRect(0, 160, "Rate", valueFuelRate, PID_ENGINE_FUEL_RATE, 80);
    updateQuarterRect(120, 160, "Timing", valueTimingAdvance, PID_TIMING_ADVANCE, 200);   

    
      

    break;
    case 2:
    //TEMPS
    if (!debug){
      obd.read(PID_AMBIENT_TEMP, valueAmbient);
      obd.read(PID_INTAKE_TEMP, valueIntake);
      obd.read(PID_COOLANT_TEMP, valueCoolant);
      obd.read(PID_MAF_FLOW, valueMAFFlow);
 //     obd.read(PID_ENGINE_OIL_TEMP, valueEngine);
    }else{
     valueCoolant=random(0,60);
     valueAmbient=random(0,60);
     valueIntake=random(0,200);
     valueMAFFlow=random(0,655);
//     valueEngine=random(0,200);
    } 
    
//    updateQuarterRect(0, 40, "Oil", valueEngine, PID_ENGINE_OIL_TEMP, 220);
    updateQuarterRect(0, 40, "MAF Flow", valueMAFFlow, PID_MAF_FLOW, 400);

    updateQuarterRect(120, 40, "Coolant", valueCoolant, PID_COOLANT_TEMP, 120);

    updateQuarterRect(0, 160, "Intake", valueIntake, PID_INTAKE_TEMP, 80);
    updateQuarterRect(120, 160, "Ambient", valueAmbient, PID_AMBIENT_TEMP, 100);  
    break;
    case 3:
     //DIAGNOSTICS

    break;
    case 4:
     //DRIVE
    if (!debug){
      obd.read(PID_SPEED,valueSpeed);
      obd.read(PID_RPM, valueRPM);
      updateShiftLEDs(valueRPM);

    }else{
     valueRPM=random(0,5000);
     valueSpeed=random(0,200);
     updateShiftLEDs(valueRPM);
    } 
    
    updateQuarterRect(0, 40, "Speed", valueSpeed, PID_SPEED, 105);;
    updateQuarterRect(120, 40, "RPM", valueRPM, PID_RPM, 8000);
    
    updateQuarterRect(120, 160, "Gear", Calculate_Gear(valueRPM, valueSpeed), PPID_GEAR, 7); 
    
//    drawQuarterRect(0, 160, "Intake", valueIntake, PID_INTAKE_TEMP, 80);
//    drawQuarterRect(120, 160, "Ambient", valueAmbient, PID_AMBIENT_TEMP, 100);  
    

    break;

  }
}


// Check to see if the PID has a new value, otherwise we won't update the screen
 bool checkForNewPIDValue(int PID, int &oldValue){
   int value;
   obd.read(PID, value);
   if (value != oldValue){
     oldValue = value;
     return false;
   } else { 
     return true;
   }
 }




void drawQuarterRect(uint16_t x0, uint16_t y0, String title, int value, int type, int warning){  
  //makes a medium Value rectangle that is 1/4 of the screen tall, 1/2 wide
  drawRoundRectValue(x0,y0,120,120,8,title,value,type,warning);
}
void updateQuarterRect(uint16_t x0, uint16_t y0, String title, int value, int type, int warning){  
  //makes a medium Value rectangle that is 1/4 of the screen tall, 1/2 wide
  updateRoundRectValue(x0,y0,120,120,8,title,value,type,warning);
}



void drawRoundRectValue(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, uint16_t radius, String title, int value, int type, int warning){
  //draw the outline
  String dispString = "";
  String blank = "";
  
  tft.drawRoundRect(x0,y0,w,h,radius,ILI9341_WHITE);
  
  //put in the title
  tft.setTextSize(2);
  tft.setCursor(x0+radius,y0+3);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.print(title);
  
  //put in the  units
  tft.setTextSize(2);
  tft.setCursor((int)(x0 + w/5 + 4*10),(int)(y0 + 2*h/5+25)); // (h-radius-8)/2 + radius));
  switch(type){
    case PID_COOLANT_TEMP:
    case PID_ENGINE_OIL_TEMP:
    case PID_AMBIENT_TEMP:
    case PID_INTAKE_TEMP:
      dispString = blank + (char)247 + "C";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);
    break;
  case PID_RPM: //"RPM":
      dispString = "RPM";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);
    break; 
  case PID_SPEED: // "speed":
      dispString = "km/h";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);
    break;
   case PID_TIMING_ADVANCE: //timing
      dispString = blank + (char)247;
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);    
    break; 
    case PID_ENGINE_FUEL_RATE: //fuel rate
      dispString = blank + "L/h";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);    
    break;
    case PID_BAROMETRIC:
    case PID_INTAKE_MAP:
    case PID_FUEL_PRESSURE: //pressure (kPA)
      dispString = blank + "kPA";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);    
    break;    
    case PID_FUEL_LEVEL: 
      //percent
      dispString = blank + "%";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);    
    break;    
    case PPID_GEAR: //gear
      //Nothing
      dispString = blank;
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);   
    break;  
    case PID_MAF_FLOW: //mass air flow g/s
      //Nothing
      dispString = blank + "g/s";
      tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
      tft.print(dispString);   
    break;   
  }
  
  //now put in the value
  updateRoundRectValue(x0,y0,w,h,radius,title,value,type,warning);
}

void updateRoundRectValue(uint16_t x0, uint16_t y0, uint16_t w, uint16_t h, uint16_t radius, String title, int value, int type, int warning){
  String blank = "";
  String dispString = "";
  //prep for writing the value
  tft.setTextSize(3);
  tft.setCursor((int)(x0 + w/8), (int)(y0 + 2*h/5)); //(h-radius-8)/2 + radius));
  
  if(value > warning){

     tft.setTextColor(ILI9341_RED, ILI9341_BLACK);
  }else{
     tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  }
  dispString = blank + value + " ";
  tft.print(dispString);
 
  

}

void drawTabs(int screenIdx){
  tft.fillScreen(ILI9341_BLACK);
  tft.setTextSize(2);
  tft.setRotation(2);
  
  //Upper left (with usb at bottom)

  tft.setCursor(0,0);
  if (screenIdx == 3){
    tft.setTextColor(ILI9341_BLACK, ILI9341_CYAN);
  } else {
    tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  }
  tft.print("DIAG.");
  
  
  //upper right
  tft.setCursor(240-12*5,0);
  if (screenIdx == 4){
    tft.setTextColor(ILI9341_BLACK, ILI9341_CYAN);
  } else {
    tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  }
  tft.print("DRIVE");

 
  //Lower left
  tft.setCursor(0,304);
  if (screenIdx == 2){
    tft.setTextColor(ILI9341_BLACK, ILI9341_CYAN);
  } else {
    tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  }
  tft.print("TEMP");
  
  
  //upper left
  tft.setCursor(240-4*12,304);
  if (screenIdx == 1){
    tft.setTextColor(ILI9341_BLACK, ILI9341_CYAN);
  } else {
    tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  }
  tft.print("FUEL");
  
  
}

void updateShiftLEDs(int currentRPM){
 int shiftRPM = 4500;
 // a negative RPM means it needs to be pinged
 if (currentRPM < 0){
   obd.read(PID_RPM, currentRPM);
 }
 if (currentRPM > shiftRPM){
   digitalWrite(SHIFTNOWPIN, HIGH);
 } else {
   digitalWrite(SHIFTNOWPIN, LOW);
 }   
}

