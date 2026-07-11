char receivedChar;
boolean newData = false;

void setup() {
  // put your setup code here, to run once:
  
  //setup the serial 
  Serial.begin(9600); 
  delay(50); 

  //serial.available determines if anything in buffer
  while (!Serial.available()) { 
    Serial.write(0x01); 
    delay(300); } 
    // read the byte that Python will send over 
  recvOneChar();
  showNewData(); 
}

void loop() {
  // put your main code here, to run repeatedly:

}

void recvOneChar() {
 if (Serial.available() > 0) {
 receivedChar = Serial.read();
 newData = true;
 }
}

void showNewData() {
 if (newData == true) {
 Serial.print("This just in ... ");
 Serial.println(receivedChar);
 newData = false;
 }
}
