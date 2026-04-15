import math
import time
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

    last_filter_update = 0.0
    running = True

    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        now = time.time()
        if now - last_filter_update >= filter_interval_sec:
            update_angles(app_state)
            last_filter_update = now

        screen.fill(BG_COLOR)
        draw_stick_figure(screen, app_state)
        draw_status_panel(screen, font_small, font_medium, app_state)

        pygame.display.flip()

    pygame.quit()