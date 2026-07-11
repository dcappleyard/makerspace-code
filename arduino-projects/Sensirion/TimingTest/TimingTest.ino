void setup() {
  // put your setup code here, to run once:

  Serial.begin(115200); // initialize serial communication
}

void loop() {
  // put your main code here, to run repeatedly:
  Serial.println(millis());
}
