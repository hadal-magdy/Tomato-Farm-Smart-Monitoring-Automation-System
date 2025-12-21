# ESP32-CAM - Tomato Farm Monitoring System
# Captures images and sends to Raspberry Pi for AI detection
# Provides live MJPEG stream for user monitoring

import camera
import time
import network
from umqtt.simple import MQTTClient
import usocket as socket
import ujson

# ==================== CONFIGURATION ====================

# WiFi Settings
WIFI_SSID = "YOUR_WIFI_NAME"           # ضع اسم الشبكة
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"   # ضع كلمة السر

# Raspberry Pi Settings
RASPI_IP = "192.168.1.100"    # ⚠️ IP الـ Raspberry Pi
RASPI_PORT = 5000             # Port بتاع Flask server

# MQTT Settings
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ESP32CAM_Tomato"

# MQTT Topics
TOPIC_CAMERA_STATUS = "tomato/camera/status"
TOPIC_CAMERA_CONTROL = "tomato/camera/control"
TOPIC_ALERT = "tomato/alert"

# Camera Settings
FRAME_INTERVAL = 5      # ثواني بين كل صورة للـ AI
STREAM_PORT = 8080      # Port للـ live stream

# ==================== ESP32-CAM CLASS ====================

class TomatoCam:
    def __init__(self):
        print("🎥 Initializing ESP32-CAM...")
        
        # Initialize camera
        try:
            camera.init(0, format=camera.JPEG)
            
            # Camera settings (VGA = 640x480)
            camera.framesize(camera.FRAME_VGA)
            camera.quality(10)  # 10-63 (lower = better quality)
            camera.contrast(0)
            camera.saturation(0)
            camera.brightness(0)
            camera.speffect(camera.EFFECT_NONE)
            camera.whitebalance(camera.WB_AUTO)
            
            print("✓ Camera OK (VGA 640x480)")
            self.camera_ready = True
            
        except Exception as e:
            print("❌ Camera failed:", e)
            self.camera_ready = False
        
        self.stream_enabled = True
        self.mqtt = None
    
    def capture(self):
        """Capture single frame"""
        if not self.camera_ready:
            return None
        
        try:
            frame = camera.capture()
            print(f"📸 Captured ({len(frame)} bytes)")
            return frame
        except Exception as e:
            print("❌ Capture error:", e)
            return None
    
    def send_to_raspi(self, frame):
        """Send frame to Raspberry Pi via HTTP POST"""
        if not frame:
            return False
        
        try:
            # Create socket
            addr = socket.getaddrinfo(RASPI_IP, RASPI_PORT)[0][-1]
            s = socket.socket()
            s.settimeout(10)
            s.connect(addr)
            
            # HTTP POST
            request = (
                "POST /detect HTTP/1.1\r\n"
                f"Host: {RASPI_IP}:{RASPI_PORT}\r\n"
                "Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n"
                "\r\n"
            )
            
            s.send(request.encode())
            s.send(frame)
            
            # Read response
            response = s.recv(512)
            s.close()
            
            print("✓ Sent to Raspberry Pi")
            return True
            
        except Exception as e:
            print(f"❌ Send failed: {e}")
            return False
    
    def start_stream(self):
        """Start HTTP server for live stream"""
        try:
            addr = socket.getaddrinfo('0.0.0.0', STREAM_PORT)[0][-1]
            self.stream_socket = socket.socket()
            self.stream_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.stream_socket.bind(addr)
            self.stream_socket.listen(1)
            self.stream_socket.settimeout(1)
            print(f"✓ Stream server on port {STREAM_PORT}")
            return True
        except Exception as e:
            print(f"❌ Stream error: {e}")
            return False
    
    def handle_stream_client(self):
        """Handle stream client (non-blocking)"""
        try:
            # Try accept (non-blocking)
            try:
                cl, addr = self.stream_socket.accept()
                print(f"📹 Client: {addr}")
            except:
                return
            
            # MJPEG headers
            cl.send(b'HTTP/1.1 200 OK\r\n')
            cl.send(b'Content-Type: multipart/x-mixed-replace; boundary=frame\r\n')
            cl.send(b'\r\n')
            
            # Stream loop
            for _ in range(300):  # Max 30 sec
                if not self.stream_enabled:
                    break
                
                frame = self.capture()
                if frame:
                    try:
                        cl.send(b'--frame\r\n')
                        cl.send(b'Content-Type: image/jpeg\r\n')
                        cl.send(f'Content-Length: {len(frame)}\r\n\r\n'.encode())
                        cl.send(frame)
                        cl.send(b'\r\n')
                    except:
                        break
                
                time.sleep(0.1)  # ~10 FPS
            
            cl.close()
            print("📹 Client disconnected")
            
        except:
            pass

# ==================== WIFI ====================

def connect_wifi():
    """Connect to WiFi"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print(f"Connecting: {WIFI_SSID}")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            print(".", end="")
            time.sleep(1)
            timeout -= 1
        print()
    
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print(f"✓ WiFi OK!")
        print(f"  IP: {ip}")
        print(f"  Stream: http://{ip}:{STREAM_PORT}")
        return True
    else:
        print("❌ WiFi failed")
        return False

# ==================== MQTT ====================

def setup_mqtt(cam):
    """Setup MQTT"""
    try:
        client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
        client.set_callback(lambda t, m: mqtt_callback(t, m, cam))
        client.connect()
        client.subscribe(TOPIC_CAMERA_CONTROL)
        
        print("✓ MQTT Connected")
        client.publish(TOPIC_CAMERA_STATUS, "online")
        
        return client
    except Exception as e:
        print(f"❌ MQTT error: {e}")
        return None

def mqtt_callback(topic, msg, cam):
    """Handle MQTT commands"""
    try:
        t = topic.decode()
        m = msg.decode()
        
        print(f"📨 MQTT: {t} = {m}")
        
        if t == TOPIC_CAMERA_CONTROL:
            if m == "capture":
                frame = cam.capture()
                if frame:
                    cam.send_to_raspi(frame)
            
            elif m == "stream_on":
                cam.stream_enabled = True
                print("📹 Stream enabled")
            
            elif m == "stream_off":
                cam.stream_enabled = False
                print("📹 Stream disabled")
                
    except Exception as e:
        print(f"MQTT callback error: {e}")

# ==================== MAIN ====================

def main():
    print("\n" + "═" * 60)
    print("🎥 ESP32-CAM - TOMATO FARM")
    print("═" * 60)
    print(f"• Frame interval: {FRAME_INTERVAL}s")
    print(f"• Raspberry Pi: {RASPI_IP}:{RASPI_PORT}")
    print(f"• Stream port: {STREAM_PORT}")
    print("═" * 60 + "\n")
    
    # Init camera
    cam = TomatoCam()
    if not cam.camera_ready:
        print("❌ Camera not ready - exiting")
        return
    
    # Connect WiFi
    if not connect_wifi():
        print("❌ WiFi failed - exiting")
        return
    
    # Setup MQTT
    cam.mqtt = setup_mqtt(cam)
    
    # Start stream server
    cam.start_stream()
    
    last_frame = 0
    
    print("\n🚀 System running...\n")
    
    try:
        while True:
            now = time.time()
            
            # Check MQTT
            if cam.mqtt:
                try:
                    cam.mqtt.check_msg()
                except:
                    pass
            
            # Capture & send for AI detection
            if now - last_frame >= FRAME_INTERVAL:
                print(f"📸 Capturing for AI detection...")
                frame = cam.capture()
                
                if frame:
                    success = cam.send_to_raspi(frame)
                    if not success:
                        print("⚠️ Raspberry Pi offline?")
                
                last_frame = now
            
            # Handle stream clients
            if cam.stream_enabled:
                cam.handle_stream_client()
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n⚠️ Shutting down...")
        if cam.mqtt:
            cam.mqtt.publish(TOPIC_CAMERA_STATUS, "offline")
        print("👋 Bye!\n")

if __name__ == "__main__":
    main()