import math
import time
from collections import deque
import pygame

from config import (
    WINDOW_W,
    WINDOW_H,
    FPS,
    BG_COLOR,
    TEXT_COLOR,
    CONNECTED_COLOR,
    DISCONNECTED_COLOR,
    HOST,
    PORT,
    HEAD_RADIUS,
    TORSO_LEN,
    SHOULDER_WIDTH,
    HIP_WIDTH,
    LIMB_LENGTHS,
    DEVICE_TO_LIMB,
    ALL_LIMBS,
    FOUR_PHONE_MODE,
    LEFT_LIMB_MIRROR_SOURCE,
    HR_STALE_TIMEOUT_SEC,
    GPS_MAP_SIZE_RATIO,
    GPS_MAP_RANGE_KM,
    GPS_HISTORY_MAX_POINTS,
)
from brain import update_angles
from state import AppState


def endpoint_from_angle(start, length, angle_deg):
    angle_rad = math.radians(angle_deg)
    x = start[0] + length * math.cos(angle_rad)
    y = start[1] + length * math.sin(angle_rad)
    return (x, y)


def draw_text(screen, text, x, y, font, color=TEXT_COLOR):
    surf = font.render(text, True, color)
    screen.blit(surf, (x, y))


def is_connected(sample, now: float) -> bool:
    return sample is not None and (now - sample.last_seen) < 2.0


def get_status_source_for_limb(limb: str, limb_to_device: dict):
    device_id = limb_to_device.get(limb)
    if device_id:
        return device_id, False

    if not FOUR_PHONE_MODE:
        return None, False

    source_limb = LEFT_LIMB_MIRROR_SOURCE.get(limb)
    if source_limb is None:
        return None, False

    return limb_to_device.get(source_limb), True


def draw_heart(screen, center, bpm, connected, stale):
    x, y = center

    if not connected or stale or bpm is None:
        color = (140, 80, 80)
        label = "--"
        scale = 1.0
    else:
        color = (255, 80, 100)
        label = str(bpm)
        pulse = 1.0 + 0.08 * math.sin(time.time() * max(0.8, bpm / 30.0))
        scale = pulse

    r = 12 * scale
    left = (x - 10 * scale, y - 6 * scale)
    right = (x + 10 * scale, y - 6 * scale)
    bottom = (x, y + 18 * scale)

    pygame.draw.circle(screen, color, (int(left[0]), int(left[1])), int(r))
    pygame.draw.circle(screen, color, (int(right[0]), int(right[1])), int(r))
    points = [
        (x - 22 * scale, y),
        (x + 22 * scale, y),
        bottom,
    ]
    pygame.draw.polygon(screen, color, points)

    font = pygame.font.SysFont("Arial", 18, bold=True)
    text = font.render(label, True, (255, 80, 100))
    rect = text.get_rect(center=(x, y + 40))
    screen.blit(text, rect)


def update_hr_history(hr_history: deque, now: float, hr_snapshot: dict, hr_stale: bool, history_window_sec: float):
    bpm = hr_snapshot["bpm"] if hr_snapshot["connected"] and not hr_stale and hr_snapshot["bpm"] is not None else None
    hr_history.append((now, bpm))

    cutoff = now - history_window_sec
    while hr_history and hr_history[0][0] < cutoff:
        hr_history.popleft()


def _bpm_to_y(bpm: float, height: int, top_pad: int, bot_pad: int) -> int:
    bpm_min = 45.0
    bpm_max = 180.0
    clamped = max(bpm_min, min(bpm_max, bpm))
    usable = max(1, height - top_pad - bot_pad)
    frac = (clamped - bpm_min) / (bpm_max - bpm_min)
    return int((height - bot_pad) - frac * usable)


def simulate_ecg_sample(now: float, bpm: int, previous_bpm: int = None) -> float:
    """Generate synthetic ECG-like pulse at given time for given BPM.
    Returns value from -1 to 1, with 0 being baseline (center).
    Frequency = BPM, amplitude scales with BPM change (5 + |bpm - previous_bpm|).
    Waveform: spike up, dip down, recover to baseline (realistic heartbeat).
    """
    if bpm is None or bpm < 30 or bpm > 200:
        return 0.0

    beat_duration = 60.0 / bpm
    phase = (now % beat_duration) / beat_duration

    if previous_bpm is None:
        previous_bpm = bpm

    amplitude = (5 + abs(bpm - previous_bpm)) / 100.0
    amplitude = max(0.05, min(1.0, amplitude))

    spike_up_frac = 0.08
    spike_down_frac = 0.20
    recovery_frac = 0.30

    if phase < spike_up_frac:
        progress = phase / spike_up_frac
        return progress * amplitude
    elif phase < spike_down_frac:
        progress = (phase - spike_up_frac) / (spike_down_frac - spike_up_frac)
        return amplitude * (1.0 - 2.0 * progress)
    elif phase < recovery_frac:
        progress = (phase - spike_down_frac) / (recovery_frac - spike_down_frac)
        return -amplitude * (1.0 - progress)
    else:
        return 0.0


def draw_ecg_monitor_graph(screen, hr_snapshot: dict, hr_stale: bool, now: float, previous_bpm: int = None):
    graph_w = max(120, int(WINDOW_W * 0.15))
    graph_h = max(90, int(WINDOW_H * 0.15))
    margin = 18
    graph_x = WINDOW_W - graph_w - margin
    graph_y = WINDOW_H - graph_h * 2 - margin * 2

    overlay = pygame.Surface((graph_w, graph_h), pygame.SRCALPHA)

    grid_color = (90, 255, 120, 35)
    frame_color = (90, 255, 120, 90)
    line_color = (120, 255, 140, 220)
    baseline_color = (90, 200, 120, 60)

    pygame.draw.rect(overlay, frame_color, (0, 0, graph_w, graph_h), width=1)

    center_y = graph_h // 2
    pygame.draw.line(overlay, baseline_color, (0, center_y), (graph_w, center_y), width=1)

    for frac in (0.25, 0.5, 0.75):
        gx = int(graph_w * frac)
        pygame.draw.line(overlay, grid_color, (gx, 0), (gx, graph_h), width=1)

    bpm = hr_snapshot["bpm"]
    if not (hr_snapshot["connected"] and not hr_stale and bpm is not None):
        label_font = pygame.font.SysFont("Arial", 14, bold=True)
        label_surf = label_font.render("ECG --", True, (150, 170, 150))
        overlay.blit(label_surf, (6, 4))
        screen.blit(overlay, (graph_x, graph_y))
        return

    time_window = 2.5
    x_scale = graph_w / time_window
    y_scale = (graph_h - 12) / 2.0 * 5.0

    points = []
    num_samples = int(graph_w * 6)
    for i in range(num_samples):
        t_offset = (i / num_samples) * time_window
        sample_time = now - time_window + t_offset

        ecg_val = simulate_ecg_sample(sample_time, bpm, previous_bpm)
        x = int(t_offset * x_scale)
        y = int(center_y - ecg_val * y_scale)
        y = max(0, min(graph_h - 1, y))
        points.append((x, y))

    if len(points) >= 2:
        pygame.draw.lines(overlay, line_color, False, points, width=2)

    label_font = pygame.font.SysFont("Arial", 14, bold=True)
    label_surf = label_font.render(f"ECG {bpm}", True, (180, 255, 200))
    overlay.blit(label_surf, (6, 4))

    screen.blit(overlay, (graph_x, graph_y))


def draw_hr_monitor_graph(screen, hr_history: deque, hr_snapshot: dict, hr_stale: bool, now: float):
    graph_w = max(120, int(WINDOW_W * 0.15))
    graph_h = max(90, int(WINDOW_H * 0.15))
    margin = 18
    graph_x = WINDOW_W - graph_w - margin
    graph_y = WINDOW_H - graph_h - margin

    overlay = pygame.Surface((graph_w, graph_h), pygame.SRCALPHA)

    grid_color = (90, 255, 120, 35)
    frame_color = (90, 255, 120, 90)
    line_color = (120, 255, 140, 220)
    pulse_color = (180, 255, 190, 120)

    pygame.draw.rect(overlay, frame_color, (0, 0, graph_w, graph_h), width=1)

    for frac in (0.25, 0.5, 0.75):
        gx = int(graph_w * frac)
        gy = int(graph_h * frac)
        pygame.draw.line(overlay, grid_color, (gx, 0), (gx, graph_h), width=1)
        pygame.draw.line(overlay, grid_color, (0, gy), (graph_w, gy), width=1)

    history_window_sec = 10.0
    top_pad = 10
    bot_pad = 8

    segments = []
    segment = []

    for ts, bpm in hr_history:
        x = int(((ts - (now - history_window_sec)) / history_window_sec) * graph_w)
        x = max(0, min(graph_w - 1, x))

        if bpm is None:
            if segment:
                segments.append(segment)
                segment = []
            continue

        y = _bpm_to_y(bpm, graph_h, top_pad, bot_pad)
        segment.append((x, y))

    if segment:
        segments.append(segment)

    for seg in segments:
        if len(seg) >= 2:
            pygame.draw.lines(overlay, line_color, False, seg, width=2)

            last_x, _ = seg[-1]
            pygame.draw.line(overlay, pulse_color, (last_x, 0), (last_x, graph_h), width=1)

    label_font = pygame.font.SysFont("Arial", 14, bold=True)
    bpm = hr_snapshot["bpm"]
    if hr_snapshot["connected"] and not hr_stale and bpm is not None:
        label = f"HR {bpm}"
        label_col = (180, 255, 200)
    else:
        label = "HR --"
        label_col = (150, 170, 150)

    label_surf = label_font.render(label, True, label_col)
    overlay.blit(label_surf, (6, 4))

    screen.blit(overlay, (graph_x, graph_y))


def _latlon_to_km(lat: float, lon: float, center_lat: float, center_lon: float):
    d_lat_km = (lat - center_lat) * 111.32
    d_lon_km = (lon - center_lon) * 111.32 * math.cos(math.radians(center_lat))
    return d_lon_km, d_lat_km


def _map_point_from_latlon(lat: float, lon: float, center_lat: float, center_lon: float, graph_w: int, graph_h: int):
    d_lon_km, d_lat_km = _latlon_to_km(lat, lon, center_lat, center_lon)
    half_range = GPS_MAP_RANGE_KM / 2.0
    if abs(d_lon_km) > half_range or abs(d_lat_km) > half_range:
        return None

    x = int(((d_lon_km + half_range) / GPS_MAP_RANGE_KM) * graph_w)
    y = int((1.0 - ((d_lat_km + half_range) / GPS_MAP_RANGE_KM)) * graph_h)
    return (max(0, min(graph_w - 1, x)), max(0, min(graph_h - 1, y)))


def _simulate_ski_point(start_lat: float, start_lon: float, progress: float):
    p = max(0.0, min(1.0, progress))

    down_km = 2.2 * p
    drift_km = 0.8 * p
    snake_km = 0.7 * math.sin(p * math.pi * 7.0) * (1.0 - 0.35 * p)

    x_km = drift_km + snake_km
    y_km = -down_km

    lat = start_lat + (y_km / 111.32)
    lon = start_lon + (x_km / (111.32 * max(0.2, math.cos(math.radians(start_lat)))))
    return lat, lon


def draw_gps_map(screen, app_state: AppState, now: float, gps_override=None, sim_state="off"):
    graph_w = max(260, int(WINDOW_W * GPS_MAP_SIZE_RATIO))
    graph_h = max(180, int(WINDOW_H * GPS_MAP_SIZE_RATIO))
    margin = 18
    graph_x = margin
    graph_y = WINDOW_H - graph_h - margin

    overlay = pygame.Surface((graph_w, graph_h), pygame.SRCALPHA)

    frame_color = (140, 170, 210, 140)
    grid_color = (110, 140, 180, 55)
    center_color = (255, 85, 85)
    history_color = (80, 170, 255)
    text_color = (210, 220, 240)
    stale_color = (180, 120, 120)

    pygame.draw.rect(overlay, frame_color, (0, 0, graph_w, graph_h), width=2)

    for i in range(1, 5):
        gx = int((i / 5.0) * graph_w)
        gy = int((i / 5.0) * graph_h)
        pygame.draw.line(overlay, grid_color, (gx, 0), (gx, graph_h), width=1)
        pygame.draw.line(overlay, grid_color, (0, gy), (graph_w, gy), width=1)

    cx = graph_w // 2
    cy = graph_h // 2
    pygame.draw.line(overlay, grid_color, (cx, 0), (cx, graph_h), width=1)
    pygame.draw.line(overlay, grid_color, (0, cy), (graph_w, cy), width=1)

    if gps_override is not None:
        provider = "simulation"
        latitude = gps_override["latitude"]
        longitude = gps_override["longitude"]
        history = gps_override["history"]
        now_connected = True
    else:
        gps = app_state.get_gps_snapshot()
        provider = gps["provider"]
        latitude = gps["latitude"]
        longitude = gps["longitude"]
        history = gps["history"]

        now_connected = False
        if provider is not None:
            snapshot = app_state.snapshot_devices()
            sample = snapshot.get(provider)
            if sample is not None:
                now_connected = (now - sample.last_seen) < 2.0

    clear_w = 58
    clear_h = 24
    clear_x = graph_w - clear_w - 8
    clear_y = graph_h - clear_h - 8
    clear_rect_screen = (graph_x + clear_x, graph_y + clear_y, clear_w, clear_h)

    sim_w = 90
    sim_h = 24
    sim_x = clear_x - sim_w - 8
    sim_y = clear_y
    sim_rect_screen = (graph_x + sim_x, graph_y + sim_y, sim_w, sim_h)

    if latitude is not None and longitude is not None:
        if len(history) > GPS_HISTORY_MAX_POINTS:
            history = history[-GPS_HISTORY_MAX_POINTS:]

        for lat, lon in history:
            point = _map_point_from_latlon(lat, lon, latitude, longitude, graph_w, graph_h)
            if point is not None:
                pygame.draw.circle(overlay, history_color, point, 1)

        pygame.draw.circle(overlay, center_color, (cx, cy), 4)

    title_font = pygame.font.SysFont("Arial", 15, bold=True)
    meta_font = pygame.font.SysFont("Arial", 13)

    title = f"GPS Map ({GPS_MAP_RANGE_KM:g}x{GPS_MAP_RANGE_KM:g} km)"
    overlay.blit(title_font.render(title, True, text_color), (8, 6))

    if provider is None:
        status = "provider: none"
        status_col = stale_color
    elif now_connected:
        status = f"provider: {provider}"
        status_col = text_color
    else:
        status = f"provider: {provider} (stale)"
        status_col = stale_color

    overlay.blit(meta_font.render(status, True, status_col), (8, 26))

    if latitude is not None and longitude is not None:
        coord_text = f"lat {latitude:.6f}, lon {longitude:.6f}"
    else:
        coord_text = "lat ---, lon ---"
    overlay.blit(meta_font.render(coord_text, True, text_color), (8, 44))

    pygame.draw.rect(overlay, (200, 210, 235, 140), (clear_x, clear_y, clear_w, clear_h), width=1)
    clear_label = meta_font.render("Clear", True, (220, 230, 245))
    clear_label_rect = clear_label.get_rect(center=(clear_x + clear_w // 2, clear_y + clear_h // 2))
    overlay.blit(clear_label, clear_label_rect)

    if sim_state == "running":
        sim_text = "Simulating"
        sim_color = (160, 170, 185)
        sim_border = (160, 170, 185, 90)
    elif sim_state == "finished":
        sim_text = "Quit"
        sim_color = (240, 220, 220)
        sim_border = (220, 185, 185, 170)
    else:
        sim_text = "Simulate"
        sim_color = (220, 230, 245)
        sim_border = (200, 210, 235, 170)

    pygame.draw.rect(overlay, sim_border, (sim_x, sim_y, sim_w, sim_h), width=1)
    sim_label = meta_font.render(sim_text, True, sim_color)
    sim_label_rect = sim_label.get_rect(center=(sim_x + sim_w // 2, sim_y + sim_h // 2))
    overlay.blit(sim_label, sim_label_rect)

    screen.blit(overlay, (graph_x, graph_y))
    return clear_rect_screen, sim_rect_screen


def draw_status_panel(screen, font_small, font_medium, app_state: AppState):
    panel_x = 20
    panel_y = 20

    draw_text(screen, f"Flask listening on http://{HOST}:{PORT}/sensor", panel_x, panel_y, font_small)
    draw_text(screen, "Limb status", panel_x, panel_y + 30, font_medium)

    snapshot = app_state.snapshot_devices()
    y = panel_y + 70
    now = time.time()

    limb_to_device = {limb: device for device, limb in DEVICE_TO_LIMB.items()}

    for limb in ALL_LIMBS:
        device_id, is_mirrored = get_status_source_for_limb(limb, limb_to_device)
        sample = snapshot.get(device_id) if device_id else None
        connected = is_connected(sample, now)

        if connected:
            if is_mirrored:
                source_limb = LEFT_LIMB_MIRROR_SOURCE[limb]
                text = f"{limb} | mirror({source_limb}) via {device_id} | pitch={sample.pitch_rad:+.3f}"
            else:
                text = f"{limb} | {device_id} | pitch={sample.pitch_rad:+.3f}"
            color = CONNECTED_COLOR
        else:
            if is_mirrored:
                source_limb = LEFT_LIMB_MIRROR_SOURCE[limb]
                text = f"{limb} | mirror({source_limb})"
            else:
                text = f"{limb}"
            color = DISCONNECTED_COLOR

        draw_text(screen, text, panel_x, y, font_small, color)
        y += 28

    y += 14
    draw_text(screen, "Heart rate", panel_x, y, font_medium)
    y += 32

    hr = app_state.get_hr_snapshot()
    hr_stale = (time.time() - hr["last_seen"]) > HR_STALE_TIMEOUT_SEC if hr["last_seen"] else True

    if hr["connected"] and not hr_stale and hr["bpm"] is not None:
        hr_text = f"Garmin HRM | connected | {hr['bpm']} bpm"
        hr_color = CONNECTED_COLOR
    else:
        hr_text = f"Garmin HRM | {hr['status_text']}"
        hr_color = DISCONNECTED_COLOR

    draw_text(screen, hr_text, panel_x, y, font_small, hr_color)


def draw_stick_figure(screen, app_state: AppState):
    angles = app_state.get_smoothed_angles_copy()

    cx = WINDOW_W // 2 + 170
    top_y = 170

    head_center = (cx, top_y)
    neck = (cx, top_y + HEAD_RADIUS + 12)
    hip_center = (cx, neck[1] + TORSO_LEN)

    left_shoulder = (cx - SHOULDER_WIDTH // 2, neck[1] + 8)
    right_shoulder = (cx + SHOULDER_WIDTH // 2, neck[1] + 8)

    left_hip = (cx - HIP_WIDTH // 2, hip_center[1])
    right_hip = (cx + HIP_WIDTH // 2, hip_center[1])

    upperarm_right_end = endpoint_from_angle(
        right_shoulder,
        LIMB_LENGTHS["upperarm_right"],
        angles["upperarm_right"],
    )
    forearm_right_end = endpoint_from_angle(
        upperarm_right_end,
        LIMB_LENGTHS["forearm_right"],
        angles["forearm_right"],
    )

    upperarm_left_end = endpoint_from_angle(
        left_shoulder,
        LIMB_LENGTHS["upperarm_left"],
        angles["upperarm_left"],
    )
    forearm_left_end = endpoint_from_angle(
        upperarm_left_end,
        LIMB_LENGTHS["forearm_left"],
        angles["forearm_left"],
    )

    upperleg_right_end = endpoint_from_angle(
        right_hip,
        LIMB_LENGTHS["upperleg_right"],
        angles["upperleg_right"],
    )
    lowerleg_right_end = endpoint_from_angle(
        upperleg_right_end,
        LIMB_LENGTHS["lowerleg_right"],
        angles["lowerleg_right"],
    )

    upperleg_left_end = endpoint_from_angle(
        left_hip,
        LIMB_LENGTHS["upperleg_left"],
        angles["upperleg_left"],
    )
    lowerleg_left_end = endpoint_from_angle(
        upperleg_left_end,
        LIMB_LENGTHS["lowerleg_left"],
        angles["lowerleg_left"],
    )

    pygame.draw.circle(screen, (240, 240, 240), (int(head_center[0]), int(head_center[1])), HEAD_RADIUS, width=3)
    pygame.draw.line(screen, (240, 240, 240), neck, hip_center, width=4)
    pygame.draw.line(screen, (180, 180, 180), left_shoulder, right_shoulder, width=3)
    pygame.draw.line(screen, (180, 180, 180), left_hip, right_hip, width=3)

    pygame.draw.line(screen, (255, 180, 120), right_shoulder, upperarm_right_end, width=6)
    pygame.draw.line(screen, (255, 140, 80), upperarm_right_end, forearm_right_end, width=6)

    pygame.draw.line(screen, (160, 200, 255), left_shoulder, upperarm_left_end, width=6)
    pygame.draw.line(screen, (100, 180, 255), upperarm_left_end, forearm_left_end, width=6)

    pygame.draw.line(screen, (255, 220, 120), right_hip, upperleg_right_end, width=7)
    pygame.draw.line(screen, (240, 190, 90), upperleg_right_end, lowerleg_right_end, width=7)

    pygame.draw.line(screen, (180, 255, 180), left_hip, upperleg_left_end, width=7)
    pygame.draw.line(screen, (130, 220, 130), upperleg_left_end, lowerleg_left_end, width=7)

    joint_points = [
        neck,
        hip_center,
        left_shoulder,
        right_shoulder,
        upperarm_left_end,
        upperarm_right_end,
        forearm_left_end,
        forearm_right_end,
        left_hip,
        right_hip,
        upperleg_left_end,
        upperleg_right_end,
        lowerleg_left_end,
        lowerleg_right_end,
    ]

    for p in joint_points:
        pygame.draw.circle(screen, (240, 240, 240), (int(p[0]), int(p[1])), 6)

    hr = app_state.get_hr_snapshot()
    hr_stale = (time.time() - hr["last_seen"]) > HR_STALE_TIMEOUT_SEC if hr["last_seen"] else True
    heart_center = (cx, neck[1] + 65)
    draw_heart(screen, heart_center, hr["bpm"], hr["connected"], hr_stale)


def run_visualizer(app_state: AppState, filter_interval_sec: float):
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("Stick Figure IMU Prototype")
    clock = pygame.time.Clock()

    font_small = pygame.font.SysFont("Arial", 20)
    font_medium = pygame.font.SysFont("Arial", 24)
    hr_history = deque()
    history_window_sec = 10.0
    previous_bpm = None
    clear_gps_rect = None
    sim_gps_rect = None
    sim_state = "off"
    sim_start_time = None
    sim_last_sample_time = 0.0
    sim_start_lat = None
    sim_start_lon = None
    sim_current = None
    sim_history = []

    last_filter_update = 0.0
    running = True

    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                if clear_gps_rect is not None:
                    x, y, w, h = clear_gps_rect
                    if x <= mx <= x + w and y <= my <= y + h:
                        if sim_state == "off":
                            app_state.clear_gps_history()
                        else:
                            sim_history = [sim_current] if sim_current is not None else []

                if sim_gps_rect is not None:
                    x, y, w, h = sim_gps_rect
                    if x <= mx <= x + w and y <= my <= y + h:
                        if sim_state == "off":
                            gps_now = app_state.get_gps_snapshot()
                            sim_start_lat = gps_now["latitude"] if gps_now["latitude"] is not None else 46.8182
                            sim_start_lon = gps_now["longitude"] if gps_now["longitude"] is not None else 8.2275
                            sim_start_time = time.time()
                            sim_last_sample_time = 0.0
                            sim_current = (sim_start_lat, sim_start_lon)
                            sim_history = [sim_current]
                            sim_state = "running"
                        elif sim_state == "finished":
                            sim_state = "off"
                            sim_start_time = None
                            sim_current = None
                            sim_history = []
                            app_state.clear_gps_history()

        now = time.time()
        if now - last_filter_update >= filter_interval_sec:
            update_angles(app_state)
            last_filter_update = now

        if sim_state == "running" and sim_start_time is not None:
            duration = 10.0
            elapsed = now - sim_start_time
            progress = min(1.0, elapsed / duration)

            if now - sim_last_sample_time >= 0.04:
                lat, lon = _simulate_ski_point(sim_start_lat, sim_start_lon, progress)
                sim_current = (lat, lon)
                if not sim_history or sim_history[-1] != sim_current:
                    sim_history.append(sim_current)
                sim_last_sample_time = now

            if progress >= 1.0:
                sim_state = "finished"

        screen.fill(BG_COLOR)
        draw_stick_figure(screen, app_state)
        draw_status_panel(screen, font_small, font_medium, app_state)

        gps_override = None
        if sim_state in ("running", "finished") and sim_current is not None:
            gps_override = {
                "latitude": sim_current[0],
                "longitude": sim_current[1],
                "history": list(sim_history),
            }

        clear_gps_rect, sim_gps_rect = draw_gps_map(
            screen,
            app_state,
            now,
            gps_override=gps_override,
            sim_state=sim_state,
        )

        hr = app_state.get_hr_snapshot()
        hr_stale = (now - hr["last_seen"]) > HR_STALE_TIMEOUT_SEC if hr["last_seen"] else True
        update_hr_history(hr_history, now, hr, hr_stale, history_window_sec)
        draw_ecg_monitor_graph(screen, hr, hr_stale, now, previous_bpm)
        if hr["bpm"] is not None and hr["connected"] and not hr_stale:
            previous_bpm = hr["bpm"]
        draw_hr_monitor_graph(screen, hr_history, hr, hr_stale, now)

        pygame.display.flip()

    pygame.quit()