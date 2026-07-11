//Functions specific to the 2012 R56 Mini Cooper S



//R56 Getrag G253 gear ratios
//#define GETRAG1 3.308
#define GETRAG12 (3.308 + 2.13) / 2
//#define GETRAG2 2.13
#define GETRAG23 (2.13 + 1.483) / 2
//#define GETRAG3 1.483
#define GETRAG34 (1.483 + 1.139) / 2
//#define GETRAG4 1.139
#define GETRAG45 (1.139 + 0.949) / 2
//#define GETRAG5 0.949
#define GETRAG56 (0.949 + 0.816) / 2
//#define GETRAG6 0.816
//#define GETRAGR 3.231


//Wheel diameter (195/55 R 16)
#define OUTTER_WHEEL_DIA 620.9 //16*25.4+2*.55*195  in mm




int Calculate_Gear(int RPM, int velocity){
  float wheelRPM, measuredGearRatio;
// Attempts to calculate the current gear selection based on the speed and RPM values, velocity in km/h

//Calculate wheel RPM
 // wheelRPM = (velocity*1000/60)/(OUTTER_WHEEL_DIA/1000*3.14159);
  measuredGearRatio = (float)RPM*.516/((float)velocity*1000/60);//RPM/wheelRPM;
  
  if (measuredGearRatio >= 3.5 || measuredGearRatio < 0.7){
    //Out of gear / clutch in
    return 0;
  } else if (measuredGearRatio < 3.5 && measuredGearRatio >= GETRAG12){
    //in first
    return 1;
  } else if (measuredGearRatio < GETRAG12 && measuredGearRatio >= GETRAG23){
    //in second
    return 2;
  } else if (measuredGearRatio < GETRAG23 && measuredGearRatio >= GETRAG34){
    //in third
    return 3;
  } else if (measuredGearRatio < GETRAG34 && measuredGearRatio >= GETRAG45){
    //in fourth
    return 4;  
  } else if (measuredGearRatio < GETRAG45 && measuredGearRatio >= GETRAG56){
    //in fifth
    return 5;
  } else if (measuredGearRatio < GETRAG56 && measuredGearRatio >= 0.7){
    //in sixth
    return 6;
  }

  
}

