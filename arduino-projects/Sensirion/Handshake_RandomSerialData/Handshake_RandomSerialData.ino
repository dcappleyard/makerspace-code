
char receivedChar;
boolean newData = false;
int ranNum;


void setup() {

  //setup the serial 
  Serial.begin(9600); 
  delay(50); 
  pinMode(13, OUTPUT);
  digitalWrite(13, HIGH);
  //serial.available determines if anything in buffer
  while (!Serial.available()) { 
    Serial.println(111); 
    delay(300); } 
    // read the byte that Python will send over 
  recvOneChar();
  showNewData(); 
  digitalWrite(13, LOW);
}

void loop() {
    ranNum = random(0,255);
    Serial.println(ranNum);
    delay(100);
 
}

