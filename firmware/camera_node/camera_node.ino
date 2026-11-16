// ParkGuard Kamera-Node für ESP32-S3 (Arduino-ESP32 Core 3.x)
// Pins: Freenove ESP32-S3-WROOM CAM. Bei anderem Board Pins anpassen!
// Ablösung: Lichtschranke / Induktionsschleife / PIR an TRIGGER_PIN löst ein Foto aus.
#include <WiFi.h>
#include <HTTPClient.h>
#include "esp_camera.h"

#define WIFI_SSID   "DEIN_WLAN"
#define WIFI_PASS   "DEIN_PASSWORT"
#define SERVER_URL  "http://192.168.1.50:8000/api/camera/entry"  // oder /exit
#define DEVICE_KEY  "change-me"
#define TRIGGER_PIN 14
#define COOLDOWN_MS 8000

void setupCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = 11; c.pin_d1 = 9; c.pin_d2 = 8; c.pin_d3 = 10;
  c.pin_d4 = 12; c.pin_d5 = 18; c.pin_d6 = 17; c.pin_d7 = 16;
  c.pin_xclk = 15; c.pin_pclk = 13; c.pin_vsync = 6; c.pin_href = 7;
  c.pin_sccb_sda = 4; c.pin_sccb_scl = 5; c.pin_pwdn = -1; c.pin_reset = -1;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_UXGA;      // 1600x1200: Kennzeichen brauchen Auflösung
  c.jpeg_quality = 10;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&c) != ESP_OK) { Serial.println("Kamera-Init fehlgeschlagen"); while (1) delay(1000); }
}

void sendPhoto() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return;
  const String boundary = "----pg";
  String head = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"p.jpg\"\r\n"
                "Content-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";
  size_t len = head.length() + fb->len + tail.length();
  uint8_t *buf = (uint8_t *)ps_malloc(len);
  if (buf) {
    memcpy(buf, head.c_str(), head.length());
    memcpy(buf + head.length(), fb->buf, fb->len);
    memcpy(buf + head.length() + fb->len, tail.c_str(), tail.length());
    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
    http.addHeader("X-Device-Key", DEVICE_KEY);
    int code = http.POST(buf, len);
    Serial.printf("HTTP %d: %s\n", code, http.getString().c_str());
    http.end();
    free(buf);
  }
  esp_camera_fb_return(fb);
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIGGER_PIN, INPUT_PULLUP);
  setupCamera();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(300);
  Serial.println(WiFi.localIP());
}

void loop() {
  static uint32_t last = 0;
  if (digitalRead(TRIGGER_PIN) == LOW && millis() - last > COOLDOWN_MS) {
    last = millis();
    delay(400);              // Auto kurz ins Bild fahren lassen
    sendPhoto();
  }
  delay(20);
}
