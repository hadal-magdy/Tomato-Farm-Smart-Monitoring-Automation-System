from machine import Pin, ADC
import dht
import onewire
import ds18x20
import time
import network
from umqtt.simple import MQTTClient
import neopixel
import ujson

# ==================== ESP32 SENSOR NODE ====================
"""
ESP32 - Tomato Farm Sensor Node
- Reads sensors only
- Sends data to Raspberry Pi
- Executes commands from Raspberry Pi
- NO local automation logic
"""

# WiFi Configuration
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""

# MQTT Configuration
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ESP32_SensorNode_01"

# MQTT Topics
TOPIC_SENSORS = "tomato/sensors/data"           # Send sensor data
TOPIC_STATUS = "tomato/esp32/status"            # Status updates
TOPIC_PUMP_CONTROL = "tomato/pump/control"      # Receive pump commands
TOPIC_FAN_CONTROL = "tomato/fan/control"        # Receive fan commands
TOPIC_LIGHT_CONTROL = "tomato/growlight/control"  # Receive light commands

# ==================== PIN DEFINITIONS ====================
# Sensors
DHT22_PIN = 15              # Air temperature & humidity
DS18B20_PIN = 27            # Soil temperature
SOIL_MOISTURE_PIN = 34      # Soil moisture
LDR_PIN = 32                # Light sensor

# Actuators - RELAYS
PUMP_RELAY_PIN = 13         # Water pump relay
FAN_RELAY_PIN = 5           # Cooling fan relay
GROWLIGHT_PIN = 14          # NeoPixel grow light

# ==================== SENSOR NODE CLASS ====================
class SensorNode:
    def __init__(self):
        print("📡 Initializing ESP32 Sensor Node...")
        
        # Sensors
        self.dht = dht.DHT22(Pin(DHT22_PIN))
        self.ds_pin = Pin(DS18B20_PIN)
        self.ds = ds18x20.DS18X20(onewire.OneWire(self.ds_pin))
        self.ds_roms = self.ds.scan()
        self.soil = ADC(Pin(SOIL_MOISTURE_PIN))
        self.soil.atten(ADC.ATTN_11DB)
        self.ldr = ADC(Pin(LDR_PIN))
        self.ldr.atten(ADC.ATTN_11DB)
        
        # Relays (Active HIGH)
        self.pump = Pin(PUMP_RELAY_PIN, Pin.OUT)
        self.pump.value(0)
        self.pump_state = False
        
        self.fan = Pin(FAN_RELAY_PIN, Pin.OUT)
        self.fan.value(0)
        self.fan_state = False
        
        # Grow Light
        self.light = neopixel.NeoPixel(Pin(GROWLIGHT_PIN), 1)
        self.light_state = False
        self.light[0] = (0, 0, 0)
        self.light.write()
        
        print("✓ Hardware ready!")
    
    def read_sensors(self):
        """Read all sensors and return as dict"""
        try:
            # DHT22
            self.dht.measure()
            time.sleep_ms(100)
            temp = self.dht.temperature()
            hum = self.dht.humidity()
            
            # DS18B20
            if self.ds_roms:
                self.ds.convert_temp()
                time.sleep_ms(750)
                soil_temp = self.ds.read_temp(self.ds_roms[0])
            else:
                soil_temp = None
            
            # Soil moisture
            moisture = int((self.soil.read() / 4095) * 100)
            
            # Light
            light = int((self.ldr.read() / 4095) * 100)
            
            return {
                'temp': round(temp, 1),
                'humidity': round(hum, 1),
                'soil_temp': round(soil_temp, 1) if soil_temp else None,
                'moisture': moisture,
                'light': light,
                'timestamp': time.time()
            }
        except Exception as e:
            print("❌ Sensor error:", e)
            return None
    
    def control_pump(self, state):
        """Execute pump control command"""
        self.pump_state = state
        self.pump.value(1 if state else 0)
        print("💧 Pump:", "ON" if state else "OFF")
    
    def control_fan(self, state):
        """Execute fan control command"""
        self.fan_state = state
        self.fan.value(1 if state else 0)
        print("🌀 Fan:", "ON" if state else "OFF")
    
    def control_light(self, state):
        """Execute light control command"""
        self.light_state = state
        if state:
            self.light[0] = (255, 255, 255)
        else:
            self.light[0] = (0, 0, 0)
        self.light.write()
        print("💡 Light:", "ON" if state else "OFF")
    
    def get_status(self):
        """Get current actuator status"""
        return {
            'pump': self.pump_state,
            'fan': self.fan_state,
            'light': self.light_state
        }
    
    def display(self, data):
        """Display sensor readings"""
        if not data:
            return
        
        print("\n" + "═" * 60)
        print("📡 ESP32 SENSOR NODE")
        print("═" * 60)
        print(f"🌡️  Air Temp:      {data['temp']}°C")
        print(f"💧 Humidity:      {data['humidity']}%")
        if data['soil_temp']:
            print(f"🌱 Soil Temp:     {data['soil_temp']}°C")
        else:
            print(f"🌱 Soil Temp:     ERROR")
        print(f"💧 Soil Moisture: {data['moisture']}%")
        print(f"☀️  Light:         {data['light']}%")
        print("─" * 60)
        print(f"💧 Pump:  {'🟢 ON ' if self.pump_state else '🔴 OFF'}")
        print(f"🌀 Fan:   {'🟢 ON ' if self.fan_state else '🔴 OFF'}")
        print(f"💡 Light: {'🟢 ON ' if self.light_state else '🔴 OFF'}")
        print("═" * 60 + "\n")

# ==================== WIFI ====================
def connect_wifi():
    """Connect to WiFi"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print("Connecting WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 10
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
    
    if wlan.isconnected():
        print("✓ WiFi OK:", wlan.ifconfig()[0])
        return True
    else:
        print("❌ WiFi Failed")
        return False

# ==================== MQTT ====================
class MQTTHandler:
    def __init__(self, node):
        self.node = node
        self.client = None
    
    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
            self.client.set_callback(self.on_message)
            self.client.connect()
            
            # Subscribe to control topics
            self.client.subscribe(TOPIC_PUMP_CONTROL)
            self.client.subscribe(TOPIC_FAN_CONTROL)
            self.client.subscribe(TOPIC_LIGHT_CONTROL)
            
            print("✓ MQTT Connected")
            self.client.publish(TOPIC_STATUS, "online")
            return True
        except Exception as e:
            print("❌ MQTT Failed:", e)
            return False
    
    def on_message(self, topic, msg):
        """Handle incoming MQTT commands from Raspberry Pi"""
        try:
            t = topic.decode()
            m = msg.decode().lower()
            
            print(f"📨 Command received: {t} = {m}")
            
            # Parse state
            state = m in ['1', 'on', 'true']
            
            # Execute command
            if t == TOPIC_PUMP_CONTROL:
                self.node.control_pump(state)
            elif t == TOPIC_FAN_CONTROL:
                self.node.control_fan(state)
            elif t == TOPIC_LIGHT_CONTROL:
                self.node.control_light(state)
            
        except Exception as e:
            print("❌ MQTT callback error:", e)
    
    def publish_sensors(self, data):
        """Publish sensor data as JSON"""
        if self.client and data:
            try:
                # Send as single JSON message
                payload = ujson.dumps(data)
                self.client.publish(TOPIC_SENSORS, payload)
                print(f"📤 Sensors published")
            except Exception as e:
                print("❌ Publish error:", e)
    
    def publish_status(self):
        """Publish actuator status"""
        if self.client:
            try:
                status = self.node.get_status()
                payload = ujson.dumps(status)
                self.client.publish(TOPIC_STATUS, payload)
            except:
                pass
    
    def check(self):
        """Check for incoming messages"""
        if self.client:
            try:
                self.client.check_msg()
            except:
                pass

# ==================== MAIN ====================
def main():
    print("\n" + "═" * 60)
    print("📡 ESP32 SENSOR NODE - TOMATO FARM")
    print("═" * 60)
    print("Role:")
    print("  • Read sensors")
    print("  • Send data to Raspberry Pi")
    print("  • Execute commands from Raspberry Pi")
    print("  • NO local automation")
    print("═" * 60 + "\n")
    
    # Initialize node
    node = SensorNode()
    
    # Connect WiFi
    if not connect_wifi():
        print("❌ Cannot run without WiFi - exiting")
        return
    
    # Connect MQTT
    mqtt = MQTTHandler(node)
    if not mqtt.connect():
        print("⚠️ MQTT not connected - will retry")
    
    last_publish = 0
    last_display = 0
    publish_interval = 5    # Send data every 5 seconds
    display_interval = 10   # Display every 10 seconds
    
    print("\n🚀 Sensor node running...\n")
    
    try:
        while True:
            now = time.time()
            
            # Check for MQTT commands
            mqtt.check()
            
            # Read sensors
            data = node.read_sensors()
            
            # Display locally
            if now - last_display >= display_interval:
                node.display(data)
                last_display = now
            
            # Publish to Raspberry Pi
            if now - last_publish >= publish_interval:
                mqtt.publish_sensors(data)
                mqtt.publish_status()
                last_publish = now
            
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\n⚠️ Shutting down...")
        node.control_pump(False)
        node.control_fan(False)
        node.control_light(False)
        if mqtt.client:
            mqtt.client.publish(TOPIC_STATUS, "offline")
        print("👋 Bye!\n")

if __name__ == "__main__":
    main()