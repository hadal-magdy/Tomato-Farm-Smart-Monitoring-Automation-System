#!/usr/bin/env python3
"""
Raspberry Pi - Tomato Farm Gateway (FastAPI AsyncIO Version)
• Async HTTP endpoints with FastAPI
• Async MQTT with aiomqtt
• Non-blocking AI detection
"""

import asyncio
import json
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import aiomqtt
import cv2
import numpy as np
from contextlib import asynccontextmanager

# ==================== CONFIGURATION ====================

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# MQTT Topics
TOPIC_SENSORS = "tomato/sensors/data"
TOPIC_ESP32_STATUS = "tomato/esp32/status"
TOPIC_CAMERA_STATUS = "tomato/camera/status"
TOPIC_MODE_CONTROL = "tomato/system/mode"
TOPIC_PUMP_CONTROL = "tomato/pump/control"
TOPIC_FAN_CONTROL = "tomato/fan/control"
TOPIC_LIGHT_CONTROL = "tomato/growlight/control"
TOPIC_ALERT = "tomato/alert"
TOPIC_RASPI_STATUS = "tomato/raspi/status"

# System Modes
MODE_MANUAL = "manual"
MODE_AUTO = "auto"
MODE_HYBRID = "hybrid"

# Thresholds
SOIL_MOISTURE_THRESHOLD = 30
TEMP_THRESHOLD = 30
LIGHT_THRESHOLD = 40
WATERING_COOLDOWN = 30

# ==================== SYSTEM STATE ====================

class SystemState:
    def __init__(self):
        self.mode = MODE_AUTO
        self.sensors = {
            'temp': None, 'humidity': None, 'soil_temp': None,
            'moisture': None, 'light': None, 'timestamp': None
        }
        self.actuators = {'pump': False, 'fan': False, 'light': False}
        self.detection = {'pest': False, 'disease': False, 'ripe': False,
                         'confidence': 0, 'timestamp': None}
        self.override = {'pump': False, 'fan': False, 'light': False}
        self.last_watering = 0
        self.esp32_online = False
        self.camera_online = False

state = SystemState()
mqtt_client = None

# ==================== MQTT CONTROL ====================

async def send_command(actuator: str, state_on: bool):
    """Send command to ESP32 via MQTT"""
    topic_map = {
        'pump': TOPIC_PUMP_CONTROL,
        'fan': TOPIC_FAN_CONTROL,
        'light': TOPIC_LIGHT_CONTROL
    }
    
    if actuator not in topic_map or not mqtt_client:
        return False
    
    try:
        command = "on" if state_on else "off"
        await mqtt_client.publish(topic_map[actuator], command)
        state.actuators[actuator] = state_on
        print(f"📤 {actuator} = {command}")
        return True
    except Exception as e:
        print(f"❌ Command failed: {e}")
        return False

async def control_pump(state_on: bool):
    return await send_command('pump', state_on)

async def control_fan(state_on: bool):
    return await send_command('fan', state_on)

async def control_light(state_on: bool):
    return await send_command('light', state_on)

async def send_alert(message: str, alert_type: str, confidence: float = 0):
    """Send alert via MQTT"""
    if mqtt_client:
        alert = {
            'message': message,
            'type': alert_type,
            'confidence': confidence,
            'timestamp': datetime.now().isoformat()
        }
        await mqtt_client.publish(TOPIC_ALERT, json.dumps(alert))
        print(f"⚠️ ALERT: {message}")

# ==================== AI DETECTION ====================

async def detect_objects(image_data: bytes):
    """
    AI Detection - Async version
    TODO: Replace with actual AI model
    """
    try:
        # Decode image (this is CPU-bound, consider using executor)
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            return {'error': 'Invalid image'}
        
        print(f"🤖 Processing: {image.shape}")
        
        # Simulate AI processing
        await asyncio.sleep(0.1)  # Simulate processing time
        
        result = {
            'pest_detected': False,
            'disease_detected': False,
            'ripe_tomatoes': 0,
            'confidence': 0.0,
            'timestamp': datetime.now().isoformat()
        }
        
        return result
        
    except Exception as e:
        print(f"❌ Detection error: {e}")
        return {'error': str(e)}

# ==================== AUTOMATION ====================

async def auto_control():
    """Async automation logic"""
    if state.mode == MODE_MANUAL:
        return
    
    sensors = state.sensors
    
    if not sensors['temp'] or sensors['moisture'] is None:
        return
    
    current_time = asyncio.get_event_loop().time()
    
    # Light control
    if sensors['light'] is not None:
        should_be_on = sensors['light'] < LIGHT_THRESHOLD
        is_on = state.actuators['light']
        is_overridden = state.override['light']
        
        if should_be_on and not is_on and not is_overridden:
            print(f"☀️ Low light ({sensors['light']}%) - Light ON")
            await control_light(True)
        elif not should_be_on and is_on and not is_overridden:
            print(f"☀️ Sufficient light - Light OFF")
            await control_light(False)
    
    # Irrigation
    if sensors['moisture'] < SOIL_MOISTURE_THRESHOLD:
        cooldown_passed = (current_time - state.last_watering) >= WATERING_COOLDOWN
        is_overridden = state.override['pump']
        
        if cooldown_passed and not is_overridden:
            print(f"💧 Soil dry ({sensors['moisture']}%) - Watering...")
            await control_pump(True)
            await asyncio.sleep(2)
            await control_pump(False)
            state.last_watering = current_time
    
    # Cooling
    should_be_on = sensors['temp'] > TEMP_THRESHOLD
    is_on = state.actuators['fan']
    is_overridden = state.override['fan']
    
    if should_be_on and not is_on and not is_overridden:
        print(f"🌡️ High temp ({sensors['temp']}°C) - Fan ON")
        await control_fan(True)
    elif not should_be_on and is_on and not is_overridden:
        print(f"🌡️ Normal temp - Fan OFF")
        await control_fan(False)

# ==================== MQTT HANDLER ====================

async def handle_mqtt_message(message):
    """Handle incoming MQTT messages"""
    try:
        topic = message.topic.value
        payload = message.payload.decode()
        
        # Sensor data
        if topic == TOPIC_SENSORS:
            data = json.loads(payload)
            state.sensors.update(data)
            state.sensors['timestamp'] = datetime.now().isoformat()
            state.esp32_online = True
            
            print(f"📊 Sensors: T={data.get('temp')}°C, M={data.get('moisture')}%")
            
            # Run automation (non-blocking)
            asyncio.create_task(auto_control())
        
        # Status updates
        elif topic == TOPIC_ESP32_STATUS:
            state.esp32_online = (payload == "online")
        
        elif topic == TOPIC_CAMERA_STATUS:
            state.camera_online = (payload == "online")
        
        # Mode change
        elif topic == TOPIC_MODE_CONTROL:
            if payload in [MODE_MANUAL, MODE_AUTO, MODE_HYBRID]:
                state.mode = payload
                state.override = {'pump': False, 'fan': False, 'light': False}
                print(f"🎛️ Mode: {state.mode}")
        
    except Exception as e:
        print(f"❌ MQTT handler error: {e}")

async def mqtt_listener():
    """Background MQTT listener"""
    global mqtt_client
    
    while True:
        try:
            async with aiomqtt.Client(MQTT_BROKER, MQTT_PORT) as client:
                mqtt_client = client
                
                # Subscribe to topics
                await client.subscribe(TOPIC_SENSORS)
                await client.subscribe(TOPIC_ESP32_STATUS)
                await client.subscribe(TOPIC_CAMERA_STATUS)
                await client.subscribe(TOPIC_MODE_CONTROL)
                
                # Publish online status
                await client.publish(TOPIC_RASPI_STATUS, "online")
                print("✓ MQTT Connected (async)")
                
                # Listen for messages
                async for message in client.messages:
                    await handle_mqtt_message(message)
                    
        except Exception as e:
            print(f"❌ MQTT error: {e}")
            await asyncio.sleep(5)  # Retry after 5 seconds

# ==================== FASTAPI APP ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle"""
    # Startup: Start MQTT listener
    mqtt_task = asyncio.create_task(mqtt_listener())
    print("🚀 MQTT listener started")
    
    yield
    
    # Shutdown: Cancel MQTT task
    mqtt_task.cancel()
    print("⚠️ MQTT listener stopped")

app = FastAPI(title="Tomato Farm Gateway", lifespan=lifespan)

@app.post('/detect')
async def detect_endpoint(request: Request):
    """Receive image from ESP32-CAM (async)"""
    try:
        image_data = await request.body()
        
        if not image_data:
            return JSONResponse({'error': 'No image'}, status_code=400)
        
        print(f"📸 Image received ({len(image_data)} bytes)")
        
        # Run AI detection (async)
        result = await detect_objects(image_data)
        
        # Update state and send alerts
        if 'pest_detected' in result:
            state.detection.update({
                'pest': result['pest_detected'],
                'disease': result['disease_detected'],
                'ripe': result['ripe_tomatoes'] > 0,
                'timestamp': result['timestamp']
            })
            
            if result['pest_detected']:
                await send_alert("🐛 Pest detected!", "pest", result.get('confidence', 0))
            
            if result['disease_detected']:
                await send_alert("🦠 Disease detected!", "disease", result.get('confidence', 0))
            
            if result['ripe_tomatoes'] > 0:
                await send_alert(f"🍅 {result['ripe_tomatoes']} tomatoes ready!", "harvest")
        
        return JSONResponse(result)
        
    except Exception as e:
        print(f"❌ Detect error: {e}")
        return JSONResponse({'error': str(e)}, status_code=500)

@app.get('/status')
async def status_endpoint():
    """System status"""
    return {
        'mode': state.mode,
        'sensors': state.sensors,
        'actuators': state.actuators,
        'detection': state.detection,
        'system_health': {
            'esp32_online': state.esp32_online,
            'camera_online': state.camera_online
        },
        'timestamp': datetime.now().isoformat()
    }

@app.post('/control')
async def control_endpoint(request: Request):
    """Manual control (async)"""
    try:
        data = await request.json()
        
        if state.mode == MODE_AUTO:
            return JSONResponse(
                {'error': 'System in AUTO mode'},
                status_code=403
            )
        
        # Execute commands (async)
        if 'pump' in data:
            await control_pump(data['pump'])
            if state.mode == MODE_HYBRID:
                state.override['pump'] = True
        
        if 'fan' in data:
            await control_fan(data['fan'])
            if state.mode == MODE_HYBRID:
                state.override['fan'] = True
        
        if 'light' in data:
            await control_light(data['light'])
            if state.mode == MODE_HYBRID:
                state.override['light'] = True
        
        return {'status': 'ok', 'actuators': state.actuators}
        
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post('/mode')
async def mode_endpoint(request: Request):
    """Change system mode"""
    try:
        data = await request.json()
        new_mode = data.get('mode')
        
        if new_mode in [MODE_MANUAL, MODE_AUTO, MODE_HYBRID]:
            state.mode = new_mode
            state.override = {'pump': False, 'fan': False, 'light': False}
            
            if mqtt_client:
                await mqtt_client.publish(TOPIC_MODE_CONTROL, new_mode)
            
            print(f"🎛️ Mode changed to: {new_mode}")
            return {'status': 'ok', 'mode': new_mode}
        else:
            return JSONResponse({'error': 'Invalid mode'}, status_code=400)
            
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

# ==================== MAIN ====================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "═" * 70)
    print("🍅 RASPBERRY PI - FASTAPI ASYNC VERSION")
    print("═" * 70)
    print("Features:")
    print("  • Async HTTP with FastAPI")
    print("  • Async MQTT with aiomqtt")
    print("  • Non-blocking AI detection")
    print("  • Same 3 modes: Manual, Auto, Hybrid")
    print("═" * 70 + "\n")
    
    # Run with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
