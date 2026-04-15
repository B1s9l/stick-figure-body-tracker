import asyncio
import threading
from bleak import BleakClient

from config import GARMIN_HR_ADDRESS, GARMIN_HR_CHAR
from state import AppState


def parse_heart_rate_measurement(data: bytearray) -> int:
    """
    BLE Heart Rate Measurement characteristic (0x2A37)
    Byte 0 = flags
    If bit0 == 0: HR is uint8 in byte 1
    If bit0 == 1: HR is uint16 in bytes 1-2
    """
    flags = data[0]
    hr_16_bit = flags & 0x01

    if hr_16_bit:
        return int.from_bytes(data[1:3], byteorder="little")
    return int(data[1])


async def hr_loop(app_state: AppState):
    def handle_hr(_sender, data: bytearray):
        try:
            bpm = parse_heart_rate_measurement(data)
            app_state.update_hr_bpm(bpm)
        except Exception as e:
            print(f"[HR] parse error: {e}")

    while True:
        try:
            app_state.set_hr_connected(False, f"connecting to {GARMIN_HR_ADDRESS}")
            async with BleakClient(GARMIN_HR_ADDRESS) as client:
                app_state.set_hr_connected(True, "connected")
                print("[HR] Connected to Garmin HRM")
                await client.start_notify(GARMIN_HR_CHAR, handle_hr)

                while client.is_connected:
                    await asyncio.sleep(1.0)

        except Exception as e:
            print(f"[HR] connection error: {e}")
            app_state.set_hr_connected(False, f"error: {e}")

        app_state.set_hr_connected(False, "reconnecting")
        await asyncio.sleep(2.0)


def run_heart_rate(app_state: AppState):
    asyncio.run(hr_loop(app_state))


def start_heart_rate_thread(app_state: AppState) -> threading.Thread:
    thread = threading.Thread(target=run_heart_rate, args=(app_state,), daemon=True)
    thread.start()
    return thread