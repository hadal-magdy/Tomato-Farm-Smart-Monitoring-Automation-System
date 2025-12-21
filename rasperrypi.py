#!/usr/bin/env python3
"""
Raspberry Pi - Tomato Farm Gateway
• Receives sensor data from ESP32 (MQTT)
• Receives images from ESP32-CAM (HTTP)
• AI Detection (placeholder for AI team)
• Controls ESP32 actuators via MQTT commands
• 3 Modes: Manual, Auto, Hybrid
• Communicates with Cloud Server
"""

import time
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify
import paho.mqtt.client as mqtt
import cv2
import numpy as np

# ==================== CONFIGURATION ====================

# Flask Server (for receiving images)
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5000

# MQTT Configuration
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "RaspberryPi_Gateway"

# MQTT Topics - Subscribe (Receive)
TOPIC_SENSORS = "tomato/sensors/data"           # From ESP32
TOPIC_ESP32_STATUS = "tomato/esp32/status"      # From ESP32
TOPIC_CAMERA_STATUS = "tomato/camera/status"    # From ESP32-CAM
TOPIC_MODE_CONTROL = "tomato/system/mode"       # From Cloud/User

# MQTT Topics - Publish (Send Commands)
TOPIC_PUMP_CONTROL = "tomato/pump/control"      # To ESP32
TOPIC_FAN_CONTROL = "tomato/fan/control"        # To ESP32
TOPIC_LIGHT_CONTROL = "tomato/growlight/control" # To ESP32
TOPIC_ALERT = "tomato/alert"                    # To Cloud/User
TOPIC_RASPI_STATUS = "tomato/raspi/status"      # Status updates

# System Modes
MODE_MANUAL = "manual"      # User controls everything
MODE_AUTO = "auto"          # Full automation
MODE_HYBRID = "hybrid"      # Auto + manual override

# Automation Thresholds
SOIL_MOISTURE_THRESHOLD = 30    # %
TEMP_THRESHOLD = 30             # °C
LIGHT_THRESHOLD = 40            # %
WATERING_COOLDOWN = 30          # seconds between watering

# Cloud Server (Backend team will provide)
CLOUD_API_URL = "http://your-backend.com/api"
CLOUD_API_KEY = "your-api-key"

# ==================== SYSTEM STATE ====================

class SystemState:
    def __init__(self):
        # Current mode
        self.mode = MODE_AUTO
        
        # Sensor data from ESP32
        self.sensors = {
            'temp': None,
            'humidity': None,
            'soil_temp': None,
            'moisture': None,
            'light': None,
            'timestamp': None
        }
        
        # Actuator states (tracked)
        self.actuators = {
            'pump': False,
            'fan': False,
            'light': False
        }
        
        # AI Detection results
        self.detection = {
            'pest': False,
            'disease': False,
            'ripe': False,
            'confidence': 0,
            'timestamp': None
        }
        
        # Manual override flags (for hybrid mode)
        self.override = {
            'pump': False,
            'fan': False,
            'light': False
        }
        
        # Last watering time
        self.last_watering = 0
        
        # System health
        self.esp32_online = False
        self.camera_online = False

state = SystemState()
mqtt_client = None

# ==================== ACTUATOR CONTROL ====================

def send_command(actuator, state_on):
    """
    Send command to ESP32 via MQTT
    
    Args:
        actuator: 'pump', 'fan', or 'light'
        state_on: True/False
    """
    if not mqtt_client:
        print("❌ MQTT not connected")
        return False
    
    topic_map = {
        'pump': TOPIC_PUMP_CONTROL,
        'fan': TOPIC_FAN_CONTROL,
        'light': TOPIC_LIGHT_CONTROL
    }
    
    if actuator not in topic_map:
        return False
    
    try:
        command = "on" if state_on else "off"
        mqtt_client.publish(topic_map[actuator], command)
        state.actuators[actuator] = state_on
        print(f"📤 Command sent: {actuator} = {command}")
        return True
    except Exception as e:
        print(f"❌ Command failed: {e}")
        return False

def control_pump(state_on):
    """Control water pump"""
    return send_command('pump', state_on)

def control_fan(state_on):
    """Control cooling fan"""
    return send_command('fan', state_on)

def control_light(state_on):
    """Control grow light"""
    return send_command('light', state_on)

def emergency_shutdown():
    """Emergency shutdown - turn off all actuators"""
    control_pump(False)
    control_fan(False)
    control_light(False)
    print("⚠️ Emergency shutdown - all actuators OFF")

# ==================== AI DETECTION ====================

def detect_objects(image_data):
    """
    AI Detection Model - PLACEHOLDER
    
    TODO: Replace with actual AI model from AI team
    
    Expected model interface:
        result = model.predict(image)
        result = {
            'pest_detected': bool,
            'disease_detected': bool,
            'ripe_tomatoes': int,
            'confidence': float,
            'detections': [...]
        }
    
    Args:
        image_data: JPEG image bytes
    
    Returns:
        dict: Detection results
    """
    
    try:
        # Decode image
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            return {'error': 'Invalid image'}
        
        print(f"🤖 Processing image: {image.shape}")
        
        # TODO: Replace this with actual AI model
        # Example: result = ai_model.predict(image)
        
        # Dummy detection for testing
        result = {
            'pest_detected': False,
            'disease_detected': False,
            'ripe_tomatoes': 0,
            'confidence': 0.0,
            'timestamp': datetime.now().isoformat()
        }
        
        print(f"🤖 AI Result: {result}")
        return result
        
    except Exception as e:
        print(f"❌ Detection error: {e}")
        return {'error': str(e)}

# ==================== AUTOMATION LOGIC ====================

def auto_control():
    """
    Automatic control based on sensor thresholds and AI
    Only runs in AUTO or HYBRID mode
    """
    
    # Skip if manual mode
    if state.mode == MODE_MANUAL:
        return
    
    sensors = state.sensors
    
    # Skip if no sensor data
    if not sensors['temp'] or sensors['moisture'] is None:
        return
    
    current_time = time.time()
    
    # === LIGHT CONTROL ===
    if sensors['light'] is not None:
        should_be_on = sensors['light'] < LIGHT_THRESHOLD
        is_on = state.actuators['light']
        is_overridden = state.override['light']
        
        if should_be_on and not is_on and not is_overridden:
            print(f"☀️ Low light ({sensors['light']}%) - Turning light ON")
            control_light(True)
        elif not should_be_on and is_on and not is_overridden:
            print(f"☀️ Sufficient light ({sensors['light']}%) - Turning light OFF")
            control_light(False)
    
    # === IRRIGATION CONTROL ===
    if sensors['moisture'] < SOIL_MOISTURE_THRESHOLD:
        cooldown_passed = (current_time - state.last_watering) >= WATERING_COOLDOWN
        is_overridden = state.override['pump']
        
        if cooldown_passed and not is_overridden:
            print(f"💧 Soil dry ({sensors['moisture']}%) - Watering...")
            control_pump(True)
            time.sleep(2)  # Water for 2 seconds
            control_pump(False)
            state.last_watering = current_time
    
    # === COOLING CONTROL ===
    should_be_on = sensors['temp'] > TEMP_THRESHOLD
    is_on = state.actuators['fan']
    is_overridden = state.override['fan']
    
    if should_be_on and not is_on and not is_overridden:
        print(f"🌡️ High temp ({sensors['temp']}°C) - Turning fan ON")
        control_fan(True)
    elif not should_be_on and is_on and not is_overridden:
        print(f"🌡️ Normal temp ({sensors['temp']}°C) - Turning fan OFF")
        control_fan(False)

# ==================== FLASK SERVER ====================

app = Flask(__name__)

@app.route('/detect', methods=['POST'])
def detect_endpoint():
    """Receive image from ESP32-CAM for AI detection"""
    try:
        image_data = request.get_data()
        
        if not image_data:
            return jsonify({'error': 'No image'}), 400
        
        print(f"📸 Image received ({len(image_data)} bytes)")
        
        # Run AI detection
        result = detect_objects(image_data)
        
        # Update state
        if 'pest_detected' in result:
            state.detection['pest'] = result['pest_detected']
            state.detection['disease'] = result['disease_detected']
            state.detection['ripe'] = result['ripe_tomatoes'] > 0
            state.detection['timestamp'] = result['timestamp']
            
            # Send alerts
            if result['pest_detected']:
                send_alert("🐛 Pest detected on plants!", "pest", result.get('confidence', 0))
            
            if result['disease_detected']:
                send_alert("🦠 Plant disease detected!", "disease", result.get('confidence', 0))
            
            if result['ripe_tomatoes'] > 0:
                send_alert(f"🍅 {result['ripe_tomatoes']} tomatoes ready to harvest!", "harvest", result.get('confidence', 0))
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Detection endpoint error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def status_endpoint():
    """System status endpoint"""
    return jsonify({
        'mode': state.mode,
        'sensors': state.sensors,
        'actuators': state.actuators,
        'detection': state.detection,
        'system_health': {
            'esp32_online': state.esp32_online,
            'camera_online': state.camera_online
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/control', methods=['POST'])
def control_endpoint():
    """Manual control endpoint (for Cloud/Web interface)"""
    try:
        data = request.get_json()
        
        if state.mode == MODE_AUTO:
            return jsonify({'error': 'System in AUTO mode - cannot control manually'}), 403
        
        # Execute commands
        if 'pump' in data:
            control_pump(data['pump'])
            if state.mode == MODE_HYBRID:
                state.override['pump'] = True
        
        if 'fan' in data:
            control_fan(data['fan'])
            if state.mode == MODE_HYBRID:
                state.override['fan'] = True
        
        if 'light' in data:
            control_light(data['light'])
            if state.mode == MODE_HYBRID:
                state.override['light'] = True
        
        return jsonify({'status': 'ok', 'actuators': state.actuators})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/mode', methods=['POST'])
def mode_endpoint():
    """Change system mode"""
    try:
        data = request.get_json()
        new_mode = data.get('mode')
        
        if new_mode in [MODE_MANUAL, MODE_AUTO, MODE_HYBRID]:
            state.mode = new_mode
            state.override = {'pump': False, 'fan': False, 'light': False}
            mqtt_client.publish(TOPIC_MODE_CONTROL, new_mode)
            print(f"🎛️ Mode changed to: {new_mode}")
            return jsonify({'status': 'ok', 'mode': new_mode})
        else:
            return jsonify({'error': 'Invalid mode'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== MQTT HANDLERS ====================

def on_mqtt_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    print(f"✓ MQTT Connected (rc={rc})")
    
    # Subscribe to topics
    client.subscribe(TOPIC_SENSORS)
    client.subscribe(TOPIC_ESP32_STATUS)
    client.subscribe(TOPIC_CAMERA_STATUS)
    client.subscribe(TOPIC_MODE_CONTROL)
    
    # Publish online status
    client.publish(TOPIC_RASPI_STATUS, "online")

def on_mqtt_message(client, userdata, msg):
    """MQTT message callback"""
    try:
        topic = msg.topic
        payload = msg.payload.decode()
        
        # Sensor data from ESP32
        if topic == TOPIC_SENSORS:
            data = json.loads(payload)
            state.sensors.update(data)
            state.sensors['timestamp'] = datetime.now().isoformat()
            state.esp32_online = True
            
            print(f"📊 Sensors: T={data.get('temp')}°C, M={data.get('moisture')}%, L={data.get('light')}%")
            
            # Run automation
            auto_control()
        
        # ESP32 status
        elif topic == TOPIC_ESP32_STATUS:
            state.esp32_online = (payload == "online")
            print(f"📡 ESP32: {payload}")
        
        # Camera status
        elif topic == TOPIC_CAMERA_STATUS:
            state.camera_online = (payload == "online")
            print(f"📹 Camera: {payload}")
        
        # Mode change command
        elif topic == TOPIC_MODE_CONTROL:
            if payload in [MODE_MANUAL, MODE_AUTO, MODE_HYBRID]:
                state.mode = payload
                state.override = {'pump': False, 'fan': False, 'light': False}
                print(f"🎛️ Mode changed to: {state.mode}")
        
    except Exception as e:
        print(f"❌ MQTT callback error: {e}")

def send_alert(message, alert_type, confidence=0):
    """Send alert via MQTT"""
    if mqtt_client:
        alert = {
            'message': message,
            'type': alert_type,
            'confidence': confidence,
            'timestamp': datetime.now().isoformat()
        }
        mqtt_client.publish(TOPIC_ALERT, json.dumps(alert))
        print(f"⚠️ ALERT: {message}")

def setup_mqtt():
    """Setup MQTT client"""
    client = mqtt.Client(MQTT_CLIENT_ID)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        return client
    except Exception as e:
        print(f"❌ MQTT connection error: {e}")
        return None

# ==================== CLOUD SYNC (PLACEHOLDER) ====================

def send_to_cloud(data):
    """
    Send data to cloud server
    TODO: Implement when backend team provides API
    """
    pass
    # Example:
    # requests.post(f"{CLOUD_API_URL}/data", 
    #               json=data, 
    #               headers={'Authorization': f'Bearer {CLOUD_API_KEY}'})

def cloud_sync_thread():
    """Background thread for cloud synchronization"""
    while True:
        try:
            if state.sensors['timestamp']:
                data = {
                    'sensors': state.sensors,
                    'actuators': state.actuators,
                    'detection': state.detection,
                    'mode': state.mode
                }
                send_to_cloud(data)
        except:
            pass
        
        time.sleep(30)  # Sync every 30 seconds

# ==================== MAIN ====================

def main():
    global mqtt_client
    
    print("\n" + "═" * 70)
    print("🍅 RASPBERRY PI - TOMATO FARM GATEWAY")
    print("═" * 70)
    print("Features:")
    print("  • Receives sensor data from ESP32 (MQTT)")
    print("  • Receives images from ESP32-CAM (HTTP)")
    print("  • AI object detection (placeholder for AI team)")
    print("  • Controls ESP32 actuators via MQTT")
    print("  • 3 Modes: Manual, Auto, Hybrid")
    print("  • Cloud communication (placeholder)")
    print("═" * 70 + "\n")
    
    # Setup MQTT
    mqtt_client = setup_mqtt()
    if not mqtt_client:
        print("⚠️ MQTT not connected - limited functionality")
    
    # Start cloud sync thread (optional)
    # threading.Thread(target=cloud_sync_thread, daemon=True).start()
    
    print(f"\n🌐 Flask server starting on port {FLASK_PORT}...")
    print(f"   Image detection: http://<raspi-ip>:{FLASK_PORT}/detect")
    print(f"   System status:   http://<raspi-ip>:{FLASK_PORT}/status")
    print(f"   Manual control:  http://<raspi-ip>:{FLASK_PORT}/control")
    print(f"   Change mode:     http://<raspi-ip>:{FLASK_PORT}/mode")
    print(f"\n🎛️  Current mode: {state.mode.upper()}")
    print("\n🚀 System running...\n")
    
    # Start Flask server
    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True)
    except KeyboardInterrupt:
        print("\n⚠️ Shutting down...")
        emergency_shutdown()
        if mqtt_client:
            mqtt_client.publish(TOPIC_RASPI_STATUS, "offline")
            mqtt_client.disconnect()
        print("👋 Bye!\n")

if __name__ == "__main__":
    main()