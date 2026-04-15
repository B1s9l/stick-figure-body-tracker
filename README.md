# Stick Figure IMU + Heart Rate Prototype

Project prototype for a body tracking suit.
The goal is to visualize limb movement and heart rate in real time.

* receives **phone motion data** from multiple iPhones via **Flask/HTTP** and the **SensorLog** (https://apps.apple.com/us/app/sensorlog/id388014573) app
* maps **motionPitch** values to limb angles
* visualizes an **8-segment stick figure** in **pygame**
* receives **heart rate** from a **Garmin HRM 600** via **BLE** using `bleak`
* shows device and sensor connection state live in the UI

This project is structured so the main app logic is split into small, understandable components.

---

## Project Structure

```text
stick_figure_app/
├── main.py          # Entry point; starts all components
├── config.py        # Global configuration
├── state.py         # Shared thread-safe app state
├── server.py        # Flask HTTP server for incoming phone sensor data
├── heart_rate.py    # Garmin HRM BLE integration using bleak
├── brain.py         # Angle computation / smoothing logic
├── visualizer.py    # Pygame window + stick figure rendering
└── requirements.txt
```

---

# Setup Guide

## 1. Install Python

Use Python 3.10+.

Check your version:

```bash
python3 --version
```

---

## 2. Create a project folder

Example:

```bash
mkdir stick_figure_app
cd stick_figure_app
```

Put all project files inside that folder.

---

## 3. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 4. Create `requirements.txt`

```txt
flask
pygame
bleak
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

---

## 5. Add the project files

Make sure your folder contains:

```text
main.py
config.py
state.py
server.py
heart_rate.py
brain.py
visualizer.py
requirements.txt
```

---

# Configuration

## 6. Set the iPhone device-to-limb mapping

Open `config.py` and edit:

```python
DEVICE_TO_LIMB = {
    "my_iOS_device": "forearm_right",
}
```

Replace the example `deviceID` values with the exact `deviceID` strings configured in SensorLog.

Example with multiple devices:

```python
DEVICE_TO_LIMB = {
    "upperarm_right_phone": "upperarm_right",
    "forearm_right_phone": "forearm_right",
    "upperarm_left_phone": "upperarm_left",
    "forearm_left_phone": "forearm_left",
    "upperleg_right_phone": "upperleg_right",
    "lowerleg_right_phone": "lowerleg_right",
    "upperleg_left_phone": "upperleg_left",
    "lowerleg_left_phone": "lowerleg_left",
}
```

Each phone must have a unique `deviceID`.

### Four-phone mirrored mode

If you only want 4 phones, enable this in `config.py`:

```python
FOUR_PHONE_MODE = True
```

In this mode, configure only these right-side limb mappings in `DEVICE_TO_LIMB`:

* `upperarm_right`
* `forearm_right`
* `upperleg_right`
* `lowerleg_right`

Left-side limbs are automatically mirrored from their corresponding right-side
source limbs (`upperarm_left <- upperarm_right`, etc.).

---

## 7. Set the Garmin HRM address

Open `config.py` and check:

```python
GARMIN_HR_ADDRESS = "80DE3980-B4F9-4B50-1064-8C6FB170344E"
```

If that address changes, replace it with the current BLE address/identifier for your Garmin HRM. Use the following script to find the HRMs BLE address.

```python
import asyncio
from bleak import BleakScanner

async def scan():
    devices = await BleakScanner.discover()
    for d in devices:
        print(d)

asyncio.run(scan())
```

---

# Running the App

## 8. Start the application

From the project folder:

```bash
source venv/bin/activate
python main.py
```

What should happen:

* Flask server starts on port `6000`
* Garmin HR thread starts trying to connect
* pygame window opens

---

# Connecting the iPhones

## 9. Find your Mac’s local IP

On macOS:

```bash
ifconfig | grep inet
```

Look for a local IP like:

```text
192.168.1.182
```

That is the IP your phones should send to.

---

## 10. Configure SensorLog on each iPhone

For each phone:

### A. Set a unique `deviceID`

In SensorLog, make sure each phone sends a different device ID.

Example:

* `upperarm_right_phone`
* `forearm_right_phone`
* `upperleg_right_phone`
* `lowerleg_right_phone`

### B. Enable the needed sensor field

You need `motionPitch` in the payload.

### C. Set upload target

Use plain HTTP, not HTTPS.

Correct example:

```text
http://192.168.1.182:6000/sensor
```

Important:

* use `http://`
* not `https://`
* same Wi-Fi as your Mac

### D. Method / format

* Method: `POST`
* Format: `JSON`

### E. Sampling/upload rate

Use whatever felt stable in your tests. High rates work, but if the signal flickers too much you can reduce the rate.

---

## 11. Check connection in the app window

For each configured limb you should see:

### Connected

Green line like:

```text
forearm_right | forearm_right_phone | pitch=+0.123
```

### Not connected

Red line like:

```text
forearm_right
```

---

# Connecting the Garmin HRM Strap

## 12. Make sure the strap is active

Wear the Garmin HRM strap so it starts broadcasting.

---

## 13. Start the app

The app will automatically try to connect to the Garmin in the background.

If successful, the status panel should show something like:

```text
Garmin HRM | connected | 74 bpm
```

And the heart icon on the torso should:

* turn active/red
* pulse in real time
* display the BPM

If not connected, the status will show reconnecting/error information.

---

# Troubleshooting

## iPhone sends nothing

Check:

* phone is on the same Wi-Fi as the Mac
* URL is correct
* using `http://`, not `https://`
* correct path `/sensor`
* SensorLog is actually running/logging

---

## Flask shows many `400` errors with binary-looking text

That almost always means the phone is trying to use **HTTPS/TLS** against your plain HTTP Flask server.

Fix the SensorLog URL:

```text
http://YOUR_MAC_IP:6000/sensor
```

not:

```text
https://YOUR_MAC_IP:6000/sensor
```

---

## Limb stays red

Check:

* device is sending
* `deviceID` exactly matches the mapping in `config.py`
* no typo in the limb name

---

## Two phones overwrite each other

That means both phones are sending the same `deviceID`.

Give each phone a unique device ID.

---

## Garmin HR does not connect

Check:

* strap is being worn and active
* correct BLE address in `config.py`
* no other app is currently connected to the HRM
* Bluetooth is enabled on your computer

---

## Motion is too jittery

Try:

* lowering SensorLog sampling/upload rate
* increasing `SMOOTHING_ALPHA` carefully
* increasing `ANGLE_DEADBAND_DEG`

---

# Development Notes

## Current design

This is a prototype designed for quick experimentation.

Currently:

* each limb uses only `motionPitch`
* no calibration
* each segment angle is computed independently

## Natural next steps

Possible future improvements:

* calibration per limb
* support for roll/yaw in addition to pitch
* constraints between upper/lower limb segments
* inverse kinematics
* recording sessions to file
* live plotting/debug views
* remote configuration UI

---

# Start Commands Summary

## Create env

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run app

```bash
python main.py
```

## Phone upload target

```text
http://YOUR_MAC_IP:6000/sensor
```

---

# License / Usage

This project is licensed under the MIT License.

You are free to use, modify, and distribute this software, provided that proper credit is given.