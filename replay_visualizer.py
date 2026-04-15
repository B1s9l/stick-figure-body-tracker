import json
import os
import time
import uuid
from collections import deque
from typing import Dict, List, Optional

import pygame

from brain import update_angles
from config import (
    ALL_LIMBS,
    DEFAULT_ANGLES_DEG,
    GPS_ACCEL_EMA_ALPHA,
    GPS_METRICS_MAX_DT_SEC,
    GPS_METRICS_MIN_DT_SEC,
    GPS_SPEED_EMA_ALPHA,
    HR_STALE_TIMEOUT_SEC,
    REPLAY_FPS,
    WINDOW_H,
    WINDOW_W,
)
from logging_runtime import SessionLogger
from state import DeviceSample
from visualizer import (
    draw_gps_map,
    draw_hr_monitor_graph,
    draw_stick_figure,
    list_log_files,
    update_hr_history,
)


def _load_events(log_path: str) -> List[Dict]:
    events = []
    if not log_path or not os.path.exists(log_path):
        return events

    with open(log_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "ts" not in event or "type" not in event:
                continue

            try:
                event["ts"] = float(event["ts"])
            except (TypeError, ValueError):
                continue

            if event["type"] not in ("sensor", "hr", "marker"):
                continue

            events.append(event)

    events.sort(key=lambda item: item["ts"])
    return events


class ReplayState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.latest_by_device: Dict[str, DeviceSample] = {}
        self.smoothed_angles_deg = {limb: DEFAULT_ANGLES_DEG[limb] for limb in ALL_LIMBS}

        self.hr_connected = False
        self.hr_bpm: Optional[int] = None
        self.hr_last_seen = 0.0
        self.hr_status_text = "not connected"

        self.gps_provider_device = None
        self.gps_coordinate_history = []
        self.markers = []
        self.gps_speed_mps = None
        self.gps_accel_mps2 = None
        self.gps_last_calc_ts = None
        self.gps_last_calc_coord = None

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        import math

        r = 6371000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)

        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c

    def _update_gps_metrics(self, ts: float, latitude: float, longitude: float):
        if self.gps_last_calc_ts is None or self.gps_last_calc_coord is None:
            self.gps_last_calc_ts = ts
            self.gps_last_calc_coord = (latitude, longitude)
            return

        dt = ts - self.gps_last_calc_ts
        if dt < GPS_METRICS_MIN_DT_SEC:
            return

        if dt > GPS_METRICS_MAX_DT_SEC:
            self.gps_last_calc_ts = ts
            self.gps_last_calc_coord = (latitude, longitude)
            return

        prev_lat, prev_lon = self.gps_last_calc_coord
        distance_m = self._haversine_m(prev_lat, prev_lon, latitude, longitude)
        inst_speed_mps = distance_m / max(dt, 1e-6)

        prev_speed = self.gps_speed_mps if self.gps_speed_mps is not None else inst_speed_mps
        smoothed_speed = prev_speed + (inst_speed_mps - prev_speed) * GPS_SPEED_EMA_ALPHA

        inst_accel_mps2 = (smoothed_speed - prev_speed) / max(dt, 1e-6)
        prev_accel = self.gps_accel_mps2 if self.gps_accel_mps2 is not None else inst_accel_mps2
        smoothed_accel = prev_accel + (inst_accel_mps2 - prev_accel) * GPS_ACCEL_EMA_ALPHA

        self.gps_speed_mps = smoothed_speed
        self.gps_accel_mps2 = smoothed_accel
        self.gps_last_calc_ts = ts
        self.gps_last_calc_coord = (latitude, longitude)

    def apply_event(self, event: Dict):
        now = time.time()
        event_type = event.get("type")

        if event_type == "sensor":
            device_id = event.get("device_id", "unknown")
            pitch_rad = float(event.get("pitch_rad", 0.0))
            latitude = event.get("latitude")
            longitude = event.get("longitude")
            accel_abs_avg = event.get("accel_abs_avg")

            self.latest_by_device[device_id] = DeviceSample(
                device_id=device_id,
                pitch_rad=pitch_rad,
                last_seen=now,
                latitude=latitude,
                longitude=longitude,
                accel_abs_avg=accel_abs_avg,
            )

            if latitude is not None and longitude is not None:
                self.gps_provider_device = device_id
                coordinate = (latitude, longitude)
                if not self.gps_coordinate_history or self.gps_coordinate_history[-1] != coordinate:
                    self.gps_coordinate_history.append(coordinate)
                self._update_gps_metrics(event["ts"], latitude, longitude)

        elif event_type == "hr":
            bpm = event.get("bpm")
            if bpm is None:
                return
            self.hr_connected = True
            self.hr_bpm = int(bpm)
            self.hr_last_seen = now
            self.hr_status_text = "connected"

        elif event_type == "marker":
            self.markers.append(
                {
                    "ts": event["ts"],
                    "type": "marker",
                    "marker_id": event.get("marker_id", ""),
                    "name": event.get("name", "Unlabeled marker"),
                    "latitude": event.get("latitude"),
                    "longitude": event.get("longitude"),
                }
            )

    def snapshot_devices(self):
        return dict(self.latest_by_device)

    def get_smoothed_angles_copy(self):
        return dict(self.smoothed_angles_deg)

    def set_smoothed_angle(self, limb: str, angle_deg: float):
        self.smoothed_angles_deg[limb] = angle_deg

    def get_smoothed_angle(self, limb: str):
        return self.smoothed_angles_deg[limb]

    def get_hr_snapshot(self):
        return {
            "connected": self.hr_connected,
            "bpm": self.hr_bpm,
            "last_seen": self.hr_last_seen,
            "status_text": self.hr_status_text,
        }

    def get_gps_snapshot(self):
        latitude = None
        longitude = None

        if self.gps_provider_device is not None:
            sample = self.latest_by_device.get(self.gps_provider_device)
            if sample is not None:
                latitude = sample.latitude
                longitude = sample.longitude

        return {
            "provider": self.gps_provider_device,
            "latitude": latitude,
            "longitude": longitude,
            "history": list(self.gps_coordinate_history),
            "markers": list(self.markers),
            "speed_mps": self.gps_speed_mps,
            "speed_kmh": self.gps_speed_mps * 3.6 if self.gps_speed_mps is not None else None,
            "accel_mps2": self.gps_accel_mps2,
        }


class ReplaySession:
    def __init__(self, log_path: str = ""):
        self.log_files = list_log_files()
        self.selected_log_path = ""
        self.events: List[Dict] = []

        self.replay_state = ReplayState()
        self.event_index = 0
        self.current_ts = 0.0
        self.first_ts = 0.0
        self.last_ts = 0.0

        if log_path and os.path.exists(log_path):
            self.selected_log_path = log_path
        elif self.log_files:
            self.selected_log_path = self.log_files[0]

        if self.selected_log_path:
            self.load_file(self.selected_log_path)

    def refresh_files(self):
        self.log_files = list_log_files()
        if not self.selected_log_path and self.log_files:
            self.load_file(self.log_files[0])

    def load_file(self, log_path: str):
        self.selected_log_path = log_path
        self.events = _load_events(log_path)
        self.replay_state.reset()
        self.event_index = 0

        if not self.events:
            self.first_ts = 0.0
            self.last_ts = 0.0
            self.current_ts = 0.0
            return

        self.first_ts = self.events[0]["ts"]
        self.last_ts = self.events[-1]["ts"]
        self.current_ts = self.first_ts
        self.seek(self.current_ts)

    def seek(self, target_ts: float):
        if not self.events:
            return

        target = max(self.first_ts, min(self.last_ts, target_ts))
        self.current_ts = target

        self.replay_state.reset()
        self.event_index = 0
        while self.event_index < len(self.events) and self.events[self.event_index]["ts"] <= target:
            self.replay_state.apply_event(self.events[self.event_index])
            self.event_index += 1

    def step(self, dt_sec: float):
        if not self.events:
            return

        self.current_ts = min(self.last_ts, self.current_ts + dt_sec)
        while self.event_index < len(self.events) and self.events[self.event_index]["ts"] <= self.current_ts:
            self.replay_state.apply_event(self.events[self.event_index])
            self.event_index += 1

    def marker_events(self):
        return [event for event in self.events if event.get("type") == "marker"]

    def _reload_after_write(self):
        if self.selected_log_path:
            self.load_file(self.selected_log_path)

    def persist_events(self):
        if not self.selected_log_path:
            return

        SessionLogger.rewrite_jsonl(self.selected_log_path, self.events)
        self._reload_after_write()

    def marker_by_id(self, marker_id: str):
        for event in self.events:
            if event.get("type") == "marker" and event.get("marker_id") == marker_id:
                return event
        return None

    def rename_marker(self, marker_id: str, new_name: str):
        marker = self.marker_by_id(marker_id)
        if marker is None:
            return

        marker["name"] = new_name.strip() or "Unlabeled marker"
        self.persist_events()

    def delete_marker(self, marker_id: str):
        self.events = [
            event
            for event in self.events
            if not (event.get("type") == "marker" and event.get("marker_id") == marker_id)
        ]
        self.persist_events()

    def create_marker(self, marker_name: str = "Unlabeled marker"):
        gps = self.replay_state.get_gps_snapshot()
        marker = {
            "ts": self.current_ts,
            "type": "marker",
            "marker_id": uuid.uuid4().hex,
            "name": marker_name.strip() or "Unlabeled marker",
            "latitude": gps.get("latitude"),
            "longitude": gps.get("longitude"),
        }
        self.events.append(marker)
        self.events.sort(key=lambda event: event["ts"])
        self.persist_events()

    def seek_marker(self, marker_id: str):
        marker = self.marker_by_id(marker_id)
        if marker is None:
            return
        self.seek(float(marker["ts"]))



def _slider_value_from_mouse(slider_rect: pygame.Rect, mouse_x: int) -> float:
    if slider_rect.width <= 0:
        return 0.0
    return max(0.0, min(1.0, (mouse_x - slider_rect.x) / slider_rect.width))


def _draw_dropdown(screen, session: ReplaySession, font):
    panel_rect = pygame.Rect(20, 20, min(500, WINDOW_W - 40), 100)
    dropdown_rect = pygame.Rect(panel_rect.x + 10, panel_rect.y + 34, panel_rect.width - 20, 30)

    pygame.draw.rect(screen, (20, 20, 20), panel_rect)
    pygame.draw.rect(screen, (180, 180, 180), panel_rect, width=2)

    header = font.render("Replay log file", True, (230, 230, 230))
    screen.blit(header, (panel_rect.x + 10, panel_rect.y + 8))

    pygame.draw.rect(screen, (32, 36, 44), dropdown_rect, border_radius=4)
    pygame.draw.rect(screen, (210, 210, 220), dropdown_rect, width=1, border_radius=4)

    label = os.path.basename(session.selected_log_path) if session.selected_log_path else "No logs found"
    text = font.render(label, True, (235, 235, 240))
    screen.blit(text, (dropdown_rect.x + 8, dropdown_rect.y + 7))

    count_text = font.render(f"entries: {len(session.events)}", True, (180, 190, 200))
    screen.blit(count_text, (panel_rect.x + 10, panel_rect.y + 70))

    return panel_rect, dropdown_rect


def _draw_dropdown_list(screen, dropdown_rect, session: ReplaySession, font):
    item_rects = []
    if not session.log_files:
        return item_rects

    row_h = 28
    menu_rect = pygame.Rect(dropdown_rect.x, dropdown_rect.bottom + 4, dropdown_rect.width, row_h * len(session.log_files))
    pygame.draw.rect(screen, (24, 28, 34), menu_rect)
    pygame.draw.rect(screen, (160, 165, 175), menu_rect, width=1)

    for index, path in enumerate(session.log_files):
        item_rect = pygame.Rect(dropdown_rect.x, dropdown_rect.bottom + 4 + (index * row_h), dropdown_rect.width, row_h)
        is_selected = path == session.selected_log_path
        fill = (60, 72, 92) if is_selected else (32, 36, 44)
        pygame.draw.rect(screen, fill, item_rect)
        pygame.draw.rect(screen, (80, 88, 100), item_rect, width=1)

        label = os.path.basename(path)
        text = font.render(label, True, (240, 240, 245))
        screen.blit(text, (item_rect.x + 6, item_rect.y + 6))
        item_rects.append((item_rect, path))

    return item_rects


def _dropdown_item_rects(dropdown_rect, session: ReplaySession):
    rects = []
    row_h = 28
    for index, path in enumerate(session.log_files):
        item_rect = pygame.Rect(dropdown_rect.x, dropdown_rect.bottom + 4 + (index * row_h), dropdown_rect.width, row_h)
        rects.append((item_rect, path))
    return rects


def _draw_slider(screen, session: ReplaySession, font):
    slider_width = int((WINDOW_W - 160) * 0.95)
    slider_x = (WINDOW_W - slider_width) // 2
    slider_rect = pygame.Rect(slider_x, WINDOW_H - 44, slider_width, 8)
    pygame.draw.rect(screen, (110, 120, 140), slider_rect)

    ratio = 0.0
    if session.events and session.last_ts > session.first_ts:
        ratio = (session.current_ts - session.first_ts) / (session.last_ts - session.first_ts)

    knob_x = slider_rect.x + int(ratio * slider_rect.width)
    knob_rect = pygame.Rect(knob_x - 6, slider_rect.y - 6, 12, 20)
    pygame.draw.rect(screen, (220, 220, 235), knob_rect)

    if session.events:
        elapsed = session.current_ts - session.first_ts
        total = session.last_ts - session.first_ts
        label = f"t={elapsed:0.2f}s / {total:0.2f}s"
    else:
        label = "No replay data"
    text = font.render(label, True, (225, 225, 235))
    screen.blit(text, (slider_rect.x, slider_rect.y - 26))

    return slider_rect, knob_rect


def _draw_play_pause_button(screen, font, is_paused: bool):
    rect = pygame.Rect(20, WINDOW_H - 54, 66, 28)
    label = "Play" if is_paused else "Pause"
    bg = (52, 92, 60) if is_paused else (120, 86, 45)

    pygame.draw.rect(screen, bg, rect, border_radius=4)
    pygame.draw.rect(screen, (220, 220, 230), rect, width=1, border_radius=4)
    text = font.render(label, True, (240, 240, 240))
    text_rect = text.get_rect(center=rect.center)
    screen.blit(text, text_rect)
    return rect


def _draw_marker_panel(screen, session: ReplaySession, font, selected_marker_id: str, marker_name_input: str, input_active: bool):
    markers = session.marker_events()
    panel_w = 320
    panel_h = 250
    panel_x = 20
    panel_y = max(20, (WINDOW_H // 2) - (panel_h // 2) - 90)
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    pygame.draw.rect(screen, (20, 20, 20), panel_rect)
    pygame.draw.rect(screen, (180, 180, 180), panel_rect, width=2)

    header = font.render(f"Markers ({len(markers)})", True, (230, 230, 230))
    screen.blit(header, (panel_x + 10, panel_y + 8))

    name_rect = pygame.Rect(panel_x + 10, panel_y + 30, panel_w - 20, 28)
    name_bg = (48, 58, 72) if input_active else (34, 38, 46)
    pygame.draw.rect(screen, name_bg, name_rect, border_radius=4)
    pygame.draw.rect(screen, (120, 190, 255) if input_active else (210, 210, 220), name_rect, width=2 if input_active else 1, border_radius=4)

    if marker_name_input:
        name_label = marker_name_input
        name_color = (240, 240, 245)
    else:
        name_label = "Marker name"
        name_color = (170, 175, 185)

    text_surface = font.render(name_label, True, name_color)
    text_pos = (name_rect.x + 8, name_rect.y + 7)
    screen.blit(text_surface, text_pos)

    if input_active:
        caret_x = min(name_rect.right - 10, text_pos[0] + text_surface.get_width() + 1)
        caret_top = name_rect.y + 6
        caret_bottom = name_rect.bottom - 6
        pygame.draw.line(screen, (240, 240, 245), (caret_x, caret_top), (caret_x, caret_bottom), width=1)

    new_rect = pygame.Rect(panel_x + 10, panel_y + 66, 146, 28)
    delete_rect = pygame.Rect(panel_x + 164, panel_y + 66, 146, 28)

    pygame.draw.rect(screen, (60, 110, 70), new_rect, border_radius=4)
    pygame.draw.rect(screen, (220, 220, 220), new_rect, width=1, border_radius=4)
    pygame.draw.rect(screen, (120, 60, 60), delete_rect, border_radius=4)
    pygame.draw.rect(screen, (220, 220, 220), delete_rect, width=1, border_radius=4)
    screen.blit(font.render("New marker", True, (245, 245, 245)), (new_rect.x + 22, new_rect.y + 6))
    screen.blit(font.render("Delete", True, (245, 245, 245)), (delete_rect.x + 49, delete_rect.y + 6))

    list_top = panel_y + 104
    list_rects = []
    if not markers:
        empty_text = font.render("No markers yet", True, (175, 180, 190))
        screen.blit(empty_text, (panel_x + 10, list_top + 6))
        return panel_rect, name_rect, new_rect, delete_rect, list_rects

    row_h = 22
    max_rows = max(1, (panel_h - (list_top - panel_y) - 10) // row_h)
    visible_markers = markers[-max_rows:]

    for index, marker in enumerate(visible_markers):
        item_y = list_top + index * row_h
        item_rect = pygame.Rect(panel_x + 10, item_y, panel_w - 20, row_h - 2)
        is_selected = marker.get("marker_id") == selected_marker_id
        fill = (56, 78, 58) if is_selected else (34, 38, 46)
        pygame.draw.rect(screen, fill, item_rect, border_radius=3)
        pygame.draw.rect(screen, (80, 90, 100), item_rect, width=1, border_radius=3)

        label = marker.get("name", "Unlabeled marker")
        ts = marker.get("ts", 0.0)
        marker_text = f"{label}  @ {ts:0.2f}s"
        screen.blit(font.render(marker_text, True, (240, 240, 245)), (item_rect.x + 6, item_rect.y + 4))
        list_rects.append((item_rect, marker.get("marker_id", "")))

    return panel_rect, name_rect, new_rect, delete_rect, list_rects


def run_replay_visualizer(initial_log_file: str = ""):
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("Stick Figure Replay")
    clock = pygame.time.Clock()

    session = ReplaySession(initial_log_file)
    font = pygame.font.SysFont("Arial", 14)

    hr_history = deque()
    history_window_sec = 10.0
    dropdown_open = False
    dragging_slider = False
    paused = True
    selected_marker_id = ""
    marker_name_input = ""
    marker_name_active = False

    def commit_marker_name():
        nonlocal selected_marker_id, marker_name_input, marker_name_active
        if selected_marker_id:
            session.rename_marker(selected_marker_id, marker_name_input)
            marker = session.marker_by_id(selected_marker_id)
            if marker is not None:
                marker_name_input = marker.get("name", marker_name_input)
        marker_name_active = False

    running = True
    while running:
        dt = clock.tick(REPLAY_FPS) / 1000.0

        session.refresh_files()

        dropdown_panel_rect, dropdown_rect = _draw_dropdown(screen, session, font)
        del dropdown_panel_rect
        dropdown_item_rects = _dropdown_item_rects(dropdown_rect, session) if dropdown_open else []
        slider_rect = pygame.Rect(80, WINDOW_H - 44, WINDOW_W - 160, 8)
        knob_rect = pygame.Rect(slider_rect.x - 6, slider_rect.y - 6, 12, 20)
        if session.events and session.last_ts > session.first_ts:
            ratio = (session.current_ts - session.first_ts) / (session.last_ts - session.first_ts)
            knob_x = slider_rect.x + int(ratio * slider_rect.width)
            knob_rect = pygame.Rect(knob_x - 6, slider_rect.y - 6, 12, 20)

        if selected_marker_id and session.marker_by_id(selected_marker_id) is None:
            selected_marker_id = ""
            marker_name_input = ""
            marker_name_active = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and marker_name_active:
                if event.key == pygame.K_RETURN:
                    commit_marker_name()
                    continue
                if event.key == pygame.K_ESCAPE:
                    if selected_marker_id:
                        marker = session.marker_by_id(selected_marker_id)
                        marker_name_input = marker.get("name", marker_name_input) if marker is not None else marker_name_input
                    marker_name_active = False
                    continue
                if event.key == pygame.K_BACKSPACE:
                    marker_name_input = marker_name_input[:-1]
                    continue
                if event.unicode and event.unicode.isprintable():
                    marker_name_input += event.unicode
                    continue
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                if knob_rect.collidepoint(mx, my) or slider_rect.collidepoint(mx, my):
                    if marker_name_active:
                        commit_marker_name()
                    dragging_slider = True
                    ratio = _slider_value_from_mouse(slider_rect, mx)
                    if session.events and session.last_ts > session.first_ts:
                        seek_ts = session.first_ts + ratio * (session.last_ts - session.first_ts)
                        session.seek(seek_ts)
                    continue

                play_pause_rect = pygame.Rect(20, WINDOW_H - 54, 66, 28)
                if play_pause_rect.collidepoint(mx, my):
                    if marker_name_active:
                        commit_marker_name()
                    paused = not paused
                    continue

                if dropdown_rect.collidepoint(mx, my):
                    if marker_name_active:
                        commit_marker_name()
                    dropdown_open = not dropdown_open
                    continue

                if marker_name_rect.collidepoint(mx, my):
                    if selected_marker_id:
                        marker = session.marker_by_id(selected_marker_id)
                        if marker is not None:
                            marker_name_input = marker.get("name", marker_name_input)
                    marker_name_active = True
                    continue

                if marker_new_rect.collidepoint(mx, my):
                    if marker_name_active:
                        commit_marker_name()
                    session.create_marker(marker_name_input or "Unlabeled marker")
                    selected_marker_id = session.marker_events()[-1]["marker_id"] if session.marker_events() else ""
                    marker_name_input = session.marker_by_id(selected_marker_id).get("name", "") if selected_marker_id else ""
                    marker_name_active = True
                    continue

                if marker_delete_rect.collidepoint(mx, my):
                    if marker_name_active:
                        commit_marker_name()
                    if selected_marker_id:
                        session.delete_marker(selected_marker_id)
                        selected_marker_id = ""
                        marker_name_input = ""
                        marker_name_active = False
                    continue

                picked_marker = None
                for item_rect, marker_id in marker_item_rects:
                    if item_rect.collidepoint(mx, my):
                        picked_marker = marker_id
                        break
                if picked_marker:
                    if marker_name_active:
                        commit_marker_name()
                    selected_marker_id = picked_marker
                    marker = session.marker_by_id(picked_marker)
                    marker_name_input = marker.get("name", "") if marker is not None else ""
                    marker_name_active = True
                    session.seek_marker(picked_marker)
                    continue

                picked = None
                if dropdown_open:
                    if marker_name_active:
                        commit_marker_name()
                    for item_rect, path in dropdown_item_rects:
                        if item_rect.collidepoint(mx, my):
                            picked = path
                            break
                    if picked is not None:
                        session.load_file(picked)
                    dropdown_open = False
                    continue

                dropdown_open = False
                if marker_name_active:
                    commit_marker_name()
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging_slider = False

        screen.fill((28, 30, 36))

        draw_stick_figure(screen, session.replay_state)

        clear_rect, sim_rect = draw_gps_map(screen, session.replay_state, time.time(), sim_state="off")
        del clear_rect, sim_rect

        hr = session.replay_state.get_hr_snapshot()
        hr_stale = (time.time() - hr["last_seen"]) > HR_STALE_TIMEOUT_SEC if hr["last_seen"] else True
        update_hr_history(hr_history, time.time(), hr, hr_stale, history_window_sec)
        draw_hr_monitor_graph(screen, hr_history, hr, hr_stale, time.time())

        dropdown_panel_rect, dropdown_rect = _draw_dropdown(screen, session, font)
        del dropdown_panel_rect
        if dropdown_open:
            dropdown_item_rects = _draw_dropdown_list(screen, dropdown_rect, session, font)

        slider_rect, knob_rect = _draw_slider(screen, session, font)
        play_pause_rect = _draw_play_pause_button(screen, font, paused)
        marker_panel_rect, marker_name_rect, marker_new_rect, marker_delete_rect, marker_item_rects = _draw_marker_panel(
            screen,
            session,
            font,
            selected_marker_id,
            marker_name_input,
            marker_name_active,
        )
        del marker_panel_rect

        mouse_buttons = pygame.mouse.get_pressed()
        if mouse_buttons[0]:
            mx, my = pygame.mouse.get_pos()
            if knob_rect.collidepoint(mx, my) or slider_rect.collidepoint(mx, my) or dragging_slider:
                dragging_slider = True
                ratio = _slider_value_from_mouse(slider_rect, mx)
                if session.events and session.last_ts > session.first_ts:
                    seek_ts = session.first_ts + ratio * (session.last_ts - session.first_ts)
                    session.seek(seek_ts)

        if session.events:
            update_angles(session.replay_state)
            if not paused:
                session.step(dt)

        pygame.display.flip()

    pygame.quit()
