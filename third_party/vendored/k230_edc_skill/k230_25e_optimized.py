# Source: github.com/Loclove/Electronics-Design-Competition-Skill@cd46b72 assets/k230/k230-25e-optimized.py
# 上游原样搬入，仅加 dzframe 补丁（见同目录 SOURCE.md）。
# Untitled - By: YaoYanbo - Fri Jul 17 2026
import gc
import math
import os
import sys
import time

import image
from machine import FPIOA, UART
from media.display import *
from media.media import *
from media.sensor import *

# ---- dianzai-workbench 补丁：dzframe/1 输出（通道见 boards/k230-vision/board.yaml；把 host/k230/dzsend.py 拷到 /sdcard）
DZ_FRAME = True          # False = 保留上游原协议
try:
    from dzsend import DzSend
except ImportError:
    DzSend = None
_dz = None


def _dz_tx(uart=None):
    global _dz
    if _dz is None and DzSend is not None:
        _dz = DzSend(uart.write) if uart is not None else DzSend.open_uart(uart_id=2, baud=115200)
    return _dz
# ---- 补丁结束

try:
    import cv_lite
except ImportError:
    cv_lite = None


# ------------------------- User configuration -------------------------

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480
DETECT_WIDTH = 400
DETECT_HEIGHT = 240
TO_IDE = True
SENSOR_FPS = 90

SENSOR_HMIRROR = False
SENSOR_VFLIP = False
USE_CV_LITE = True

UART_ENABLED = True
UART_BAUDRATE = 115200
UART_TX_PIN = 11
UART_RX_PIN = 12
UART_SEND_EVERY_N_FRAMES = 1
UART_SEND_COAST_MISSES = 12

# "xy_u16": exact 800x480 OSD coordinates, 7-byte binary packet:
# 55 AA XL XH YL YH CHECKSUM (little endian, checksum=sum(first 6)&0xFF).
# "legacy_u8": keep the previous 5-byte 0..255 scaled/inverted packet.
UART_PACKET_MODE = "xy_u16"


# ------------------------- Detector configuration -------------------------

# Official CV-Lite example values. At 400x240 this path is normally fast
# enough to keep a 60 Hz LCD fluid.
CVL_CANNY_LOW = 50
CVL_CANNY_HIGH = 150
CVL_APPROX_EPSILON = 0.04
CVL_MIN_AREA_RATIO = 0.003
CVL_MAX_ANGLE_COS = 0.45
CVL_GAUSSIAN_SIZE = 5
CVL_MAX_CONSECUTIVE_ERRORS = 3

BLACK_THRESHOLD = (0, 110)
BLOB_X_STRIDE = 2
BLOB_Y_STRIDE = 2

MIN_FRAME_AREA_RATIO = 0.003
MAX_FRAME_AREA_RATIO = 0.78
MIN_AXIS_RATIO = 0.38
MAX_AXIS_RATIO = 0.94
EXPECTED_AXIS_RATIO = 0.70
MAX_OPPOSITE_EDGE_RATIO = 2.20
MIN_ROTATED_FILL = 0.38
FRAME_EDGE_MARGIN = 3
MAX_CANDIDATES_TO_VALIDATE = 8

BORDER_DARK_MAX = 125
PAPER_WHITE_MIN = 105
BORDER_SAMPLES = (0.22, 0.50, 0.78)
INTERIOR_SAMPLES = ((0.28, 0.28), (0.72, 0.28), (0.50, 0.50),
                    (0.28, 0.72), (0.72, 0.72))
MIN_TOTAL_BORDER_HITS = 6
MIN_WHITE_SIDE_HITS = 2
MIN_WHITE_INTERIOR_HITS = 2
PAPER_OFFSET_RATIO = 0.12


# ------------------------- Tracker configuration -------------------------

ACQUIRE_CONFIRM_FRAMES = 2
MAX_TRACK_MISSES = 12
MAX_COAST_DRAW_MISSES = 12
TRACK_CENTER_GATE_RATIO = 0.95
TRACK_SIZE_RATIO_MIN = 0.58
TRACK_SIZE_RATIO_MAX = 1.70
TRACK_AXIS_RATIO_DELTA = 0.20

ROI_MARGIN_RATIO = 0.70
ROI_FULL_FRAME_AFTER_MISSES = 2

CENTER_ALPHA_STILL = 0.20
CENTER_ALPHA_SLOW = 0.40
CENTER_ALPHA_FAST = 0.80
CENTER_STILL_ERROR = 1.40
CENTER_FAST_ERROR = 7.0
CENTER_DEADBAND = 0.45
VELOCITY_BETA_STILL = 0.035
VELOCITY_BETA = 0.11
VELOCITY_BETA_FAST = 0.18
VELOCITY_STILL_DAMPING = 0.55
VELOCITY_DAMPING = 0.72
CORNER_ALPHA_STILL = 0.16
CORNER_ALPHA_SLOW = 0.32
CORNER_ALPHA_FAST = 0.62
CORNER_FAST_ERROR = 6.0
SIZE_ALPHA = 0.34

FPS_TEXT_UPDATE_FRAMES = 5
PRINT_INTERVAL = 120
GC_INTERVAL = 300

COLOR_LOCKED = (0, 255, 0)
COLOR_COAST = (255, 160, 0)
COLOR_COAST_END = (72, 72, 72)
COLOR_LINK = (255, 255, 0)
COLOR_SCREEN_CENTER = (0, 220, 255)
COLOR_TEXT = (255, 255, 255)


C_SCORE = 0
C_CORNERS = 1
C_CENTER_X = 2
C_CENTER_Y = 3
C_LONG_SIDE = 4
C_SHORT_SIDE = 5
C_AXIS_RATIO = 6
C_BBOX = 7


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def distance_squared(x1, y1, x2, y2):
    dx = x1 - x2
    dy = y1 - y2
    return dx * dx + dy * dy


def point_distance(point1, point2):
    return math.sqrt(distance_squared(
        point1[0], point1[1], point2[0], point2[1]))


def line_intersection(line1, line2):
    x1, y1, x2, y2 = line1
    x3, y3, x4, y4 = line2
    denominator = ((x1 - x2) * (y3 - y4) -
                   (y1 - y2) * (x3 - x4))
    if -0.001 < denominator < 0.001:
        return None
    cross12 = x1 * y2 - y1 * x2
    cross34 = x3 * y4 - y3 * x4
    x = (cross12 * (x3 - x4) - (x1 - x2) * cross34) / denominator
    y = (cross12 * (y3 - y4) - (y1 - y2) * cross34) / denominator
    return (x, y)


def order_corners(points):
    if len(points) != 4:
        return None
    corners = []
    center_x = 0.0
    center_y = 0.0
    for point in points:
        item = (float(point[0]), float(point[1]))
        corners.append(item)
        center_x += item[0]
        center_y += item[1]
    center_x *= 0.25
    center_y *= 0.25
    corners.sort(key=lambda p: math.atan2(
        p[1] - center_y, p[0] - center_x))

    first = 0
    first_sum = corners[0][0] + corners[0][1]
    for index in range(1, 4):
        value = corners[index][0] + corners[index][1]
        if value < first_sum:
            first = index
            first_sum = value
    return corners[first:] + corners[:first]


def polygon_area(corners):
    total = 0.0
    for index in range(4):
        next_index = (index + 1) & 3
        total += corners[index][0] * corners[next_index][1]
        total -= corners[next_index][0] * corners[index][1]
    return abs(total) * 0.5


def corners_bbox(corners):
    xs = (corners[0][0], corners[1][0], corners[2][0], corners[3][0])
    ys = (corners[0][1], corners[1][1], corners[2][1], corners[3][1])
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return (min_x, min_y, max_x - min_x, max_y - min_y)


def quadrilateral_center(corners):
    center = line_intersection(
        (corners[0][0], corners[0][1],
         corners[2][0], corners[2][1]),
        (corners[1][0], corners[1][1],
         corners[3][0], corners[3][1]))
    if center is not None:
        return center
    return ((corners[0][0] + corners[1][0] +
             corners[2][0] + corners[3][0]) * 0.25,
            (corners[0][1] + corners[1][1] +
             corners[2][1] + corners[3][1]) * 0.25)


def pixel_gray(pixel):
    if isinstance(pixel, (tuple, list)):
        if len(pixel) >= 3:
            return (int(pixel[0]) * 30 + int(pixel[1]) * 59 +
                    int(pixel[2]) * 11) // 100
        return int(pixel[0])
    value = int(pixel)
    if value <= 255:
        return value
    red = ((value >> 11) & 0x1F) * 255 // 31
    green = ((value >> 5) & 0x3F) * 255 // 63
    blue = (value & 0x1F) * 255 // 31
    return (red * 30 + green * 59 + blue * 11) // 100


def image_gray(img, x, y, width, height):
    x = int(x)
    y = int(y)
    if x < 0 or x >= width or y < 0 or y >= height:
        return -1
    return pixel_gray(img.get_pixel(x, y))


def point_is_dark(img, x, y, width, height):
    x = int(clamp(x, 1, width - 2))
    y = int(clamp(y, 1, height - 2))
    get_pixel = img.get_pixel
    return min(pixel_gray(get_pixel(x, y)),
               pixel_gray(get_pixel(x - 1, y)),
               pixel_gray(get_pixel(x + 1, y)),
               pixel_gray(get_pixel(x, y - 1)),
               pixel_gray(get_pixel(x, y + 1))) <= BORDER_DARK_MAX


def appearance_score(img, candidate):
    corners = candidate[C_CORNERS]
    width = img.width()
    height = img.height()
    scale = min(width / 400.0, height / 240.0)
    offset = clamp(candidate[C_SHORT_SIDE] * PAPER_OFFSET_RATIO,
                   4.0 * scale, 14.0 * scale)
    border_hits = 0
    inside_white = 0
    outside_white = 0

    for side in range(4):
        point1 = corners[side]
        point2 = corners[(side + 1) & 3]
        dx = point2[0] - point1[0]
        dy = point2[1] - point1[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 4.0 * scale:
            return None
        side_hits = 0
        for position in BORDER_SAMPLES:
            x = point1[0] + dx * position
            y = point1[1] + dy * position
            if point_is_dark(img, x, y, width, height):
                side_hits += 1
                border_hits += 1
        if side_hits == 0:
            return None

        inward_x = -dy / length
        inward_y = dx / length
        midpoint_x = (point1[0] + point2[0]) * 0.5
        midpoint_y = (point1[1] + point2[1]) * 0.5
        if image_gray(img,
                      midpoint_x + inward_x * offset,
                      midpoint_y + inward_y * offset,
                      width, height) >= PAPER_WHITE_MIN:
            inside_white += 1
        if image_gray(img,
                      midpoint_x - inward_x * offset,
                      midpoint_y - inward_y * offset,
                      width, height) >= PAPER_WHITE_MIN:
            outside_white += 1

    if border_hits < MIN_TOTAL_BORDER_HITS:
        return None
    if (inside_white < MIN_WHITE_SIDE_HITS or
            outside_white < MIN_WHITE_SIDE_HITS):
        return None

    interior_white = 0
    for u, v in INTERIOR_SAMPLES:
        top_x = corners[0][0] + (corners[1][0] - corners[0][0]) * u
        top_y = corners[0][1] + (corners[1][1] - corners[0][1]) * u
        bottom_x = corners[3][0] + (corners[2][0] - corners[3][0]) * u
        bottom_y = corners[3][1] + (corners[2][1] - corners[3][1]) * u
        x = top_x + (bottom_x - top_x) * v
        y = top_y + (bottom_y - top_y) * v
        if image_gray(img, x, y, width, height) >= PAPER_WHITE_MIN:
            interior_white += 1
    if interior_white < MIN_WHITE_INTERIOR_HITS:
        return None

    return (border_hits / 12.0 +
            (inside_white + outside_white) / 8.0 +
            interior_white / 5.0)


def build_candidate(points, tracker, width, height, source_score=0.0):
    corners = order_corners(points)
    if corners is None:
        return None
    x, y, box_width, box_height = corners_bbox(corners)
    if (x <= FRAME_EDGE_MARGIN or y <= FRAME_EDGE_MARGIN or
            x + box_width >= width - FRAME_EDGE_MARGIN or
            y + box_height >= height - FRAME_EDGE_MARGIN):
        return None

    area = polygon_area(corners)
    area_ratio = area / float(width * height)
    if not (MIN_FRAME_AREA_RATIO <= area_ratio <= MAX_FRAME_AREA_RATIO):
        return None

    edges = (point_distance(corners[0], corners[1]),
             point_distance(corners[1], corners[2]),
             point_distance(corners[2], corners[3]),
             point_distance(corners[3], corners[0]))
    if min(edges) < 4.0:
        return None
    opposite1 = max(edges[0], edges[2]) / min(edges[0], edges[2])
    opposite2 = max(edges[1], edges[3]) / min(edges[1], edges[3])
    if (opposite1 > MAX_OPPOSITE_EDGE_RATIO or
            opposite2 > MAX_OPPOSITE_EDGE_RATIO):
        return None

    side1 = (edges[0] + edges[2]) * 0.5
    side2 = (edges[1] + edges[3]) * 0.5
    long_side = max(side1, side2)
    short_side = min(side1, side2)
    axis_ratio = short_side / long_side
    if not (MIN_AXIS_RATIO <= axis_ratio <= MAX_AXIS_RATIO):
        return None
    fill = area / max(box_width * box_height, 1.0)
    if fill < MIN_ROTATED_FILL:
        return None

    center_x, center_y = quadrilateral_center(corners)
    if not tracker.allows(center_x, center_y,
                          long_side, short_side, axis_ratio,
                          width, height):
        return None

    ratio_score = max(
        0.0, 1.0 - abs(axis_ratio - EXPECTED_AXIS_RATIO) / 0.34)
    perspective_score = 2.0 / (opposite1 + opposite2)
    score = (ratio_score * 1.5 + perspective_score * 0.8 +
             min(fill, 1.0) * 0.5 +
             min(area_ratio / 0.15, 1.0) * 0.35 + source_score)
    if tracker.locked:
        predicted_x, predicted_y = tracker.predicted_center()
        gate = tracker.center_gate(long_side, width, height)
        error = math.sqrt(distance_squared(
            center_x, center_y, predicted_x, predicted_y))
        score += max(0.0, 1.0 - error / gate) * 4.0
        long_ratio = long_side / max(tracker.long_side, 1.0)
        short_ratio = short_side / max(tracker.short_side, 1.0)
        size_error = (abs(long_ratio - 1.0) +
                      abs(short_ratio - 1.0))
        score += max(0.0, 1.0 - size_error / 0.50) * 1.5
    return (score, corners, center_x, center_y,
            long_side, short_side, axis_ratio,
            (x, y, box_width, box_height))


class TargetTracker:
    def __init__(self):
        self.corners = [[0.0, 0.0] for _ in range(4)]
        self.reset()

    def reset(self):
        self.locked = False
        self.measured = False
        self.center_x = 0.0
        self.center_y = 0.0
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.long_side = 0.0
        self.short_side = 0.0
        self.axis_ratio = 0.0
        self.misses = 0
        self.pending = None
        self.pending_count = 0

    def predicted_center(self):
        return (self.center_x + self.velocity_x,
                self.center_y + self.velocity_y)

    def center_gate(self, long_side, width, height):
        scale = min(width / 400.0, height / 240.0)
        return max(24.0 * scale, long_side * TRACK_CENTER_GATE_RATIO)

    def allows(self, center_x, center_y, long_side, short_side,
               axis_ratio, width, height):
        if not self.locked:
            return True
        predicted_x, predicted_y = self.predicted_center()
        gate = self.center_gate(max(long_side, self.long_side),
                                width, height)
        gate *= 1.0 + self.misses * 0.35
        if distance_squared(center_x, center_y,
                            predicted_x, predicted_y) > gate * gate:
            return False
        long_ratio = long_side / max(self.long_side, 1.0)
        short_ratio = short_side / max(self.short_side, 1.0)
        return (TRACK_SIZE_RATIO_MIN <= long_ratio <= TRACK_SIZE_RATIO_MAX and
                TRACK_SIZE_RATIO_MIN <= short_ratio <= TRACK_SIZE_RATIO_MAX and
                abs(axis_ratio - self.axis_ratio) <= TRACK_AXIS_RATIO_DELTA)

    def pending_matches(self, candidate, width, height):
        if self.pending is None:
            return False
        scale = min(width / 400.0, height / 240.0)
        gate = max(16.0 * scale, candidate[C_LONG_SIDE] * 0.55)
        long_ratio = candidate[C_LONG_SIDE] / max(
            self.pending[C_LONG_SIDE], 1.0)
        short_ratio = candidate[C_SHORT_SIDE] / max(
            self.pending[C_SHORT_SIDE], 1.0)
        return (distance_squared(
                    candidate[C_CENTER_X], candidate[C_CENTER_Y],
                    self.pending[C_CENTER_X], self.pending[C_CENTER_Y]) <=
                gate * gate and
                0.55 <= long_ratio <= 1.80 and
                0.55 <= short_ratio <= 1.80 and
                abs(candidate[C_AXIS_RATIO] -
                    self.pending[C_AXIS_RATIO]) <= 0.20)

    def accept(self, candidate, width, height, first=False):
        measured_x = candidate[C_CENTER_X]
        measured_y = candidate[C_CENTER_Y]
        measured_corners = candidate[C_CORNERS]
        scale = min(width / 400.0, height / 240.0)
        if first:
            self.center_x = measured_x
            self.center_y = measured_y
            self.velocity_x = 0.0
            self.velocity_y = 0.0
            for index in range(4):
                self.corners[index][0] = measured_corners[index][0]
                self.corners[index][1] = measured_corners[index][1]
        else:
            previous_x = self.center_x
            previous_y = self.center_y
            old_vx = self.velocity_x
            old_vy = self.velocity_y
            predicted_x = previous_x + old_vx
            predicted_y = previous_y + old_vy
            residual_x = measured_x - predicted_x
            residual_y = measured_y - predicted_y
            error = math.sqrt(residual_x * residual_x + residual_y * residual_y)
            speed = math.sqrt(old_vx * old_vx + old_vy * old_vy)
            still_limit = CENTER_STILL_ERROR * scale
            fast_limit = CENTER_FAST_ERROR * scale
            deadband = CENTER_DEADBAND * scale

            if error <= deadband and speed <= still_limit:
                self.center_x = previous_x + old_vx * 0.20
                self.center_y = previous_y + old_vy * 0.20
                self.velocity_x = old_vx * VELOCITY_STILL_DAMPING
                self.velocity_y = old_vy * VELOCITY_STILL_DAMPING
            else:
                if error <= still_limit:
                    alpha = CENTER_ALPHA_STILL
                    velocity_beta = VELOCITY_BETA_STILL
                elif error >= fast_limit:
                    alpha = CENTER_ALPHA_FAST
                    velocity_beta = VELOCITY_BETA_FAST
                else:
                    alpha = CENTER_ALPHA_SLOW
                    velocity_beta = VELOCITY_BETA
                self.center_x = predicted_x + alpha * residual_x
                self.center_y = predicted_y + alpha * residual_y
                max_velocity = 35.0 * scale
                self.velocity_x = clamp(
                    old_vx + velocity_beta * residual_x,
                    -max_velocity, max_velocity)
                self.velocity_y = clamp(
                    old_vy + velocity_beta * residual_y,
                    -max_velocity, max_velocity)

            shift_x = self.center_x - previous_x
            shift_y = self.center_y - previous_y
            for index in range(4):
                px = self.corners[index][0] + shift_x
                py = self.corners[index][1] + shift_y
                corner_dx = measured_corners[index][0] - px
                corner_dy = measured_corners[index][1] - py
                corner_error = max(abs(corner_dx), abs(corner_dy))
                if corner_error <= still_limit and speed <= still_limit:
                    corner_alpha = CORNER_ALPHA_STILL
                elif corner_error >= CORNER_FAST_ERROR * scale:
                    corner_alpha = CORNER_ALPHA_FAST
                else:
                    corner_alpha = CORNER_ALPHA_SLOW
                self.corners[index][0] = px + corner_alpha * corner_dx
                self.corners[index][1] = py + corner_alpha * corner_dy

        if first:
            self.long_side = candidate[C_LONG_SIDE]
            self.short_side = candidate[C_SHORT_SIDE]
            self.axis_ratio = candidate[C_AXIS_RATIO]
        else:
            self.long_side += SIZE_ALPHA * (
                candidate[C_LONG_SIDE] - self.long_side)
            self.short_side += SIZE_ALPHA * (
                candidate[C_SHORT_SIDE] - self.short_side)
            self.axis_ratio += SIZE_ALPHA * (
                candidate[C_AXIS_RATIO] - self.axis_ratio)
        self.locked = True
        self.measured = True
        self.misses = 0
        self.pending = None
        self.pending_count = 0

    def update(self, candidate, width, height):
        self.measured = False
        if self.locked:
            if candidate is not None:
                self.accept(candidate, width, height)
            else:
                self.center_x += self.velocity_x
                self.center_y += self.velocity_y
                for corner in self.corners:
                    corner[0] += self.velocity_x
                    corner[1] += self.velocity_y
                self.velocity_x *= VELOCITY_DAMPING
                self.velocity_y *= VELOCITY_DAMPING
                self.misses += 1
                if self.misses > MAX_TRACK_MISSES:
                    self.reset()
            return self.locked

        if candidate is None:
            self.pending = None
            self.pending_count = 0
            return False
        if not self.pending_matches(candidate, width, height):
            self.pending = candidate
            self.pending_count = 1
            return False
        self.pending = candidate
        self.pending_count += 1
        if self.pending_count >= ACQUIRE_CONFIRM_FRAMES:
            self.accept(candidate, width, height, first=True)
        return self.locked

    def search_roi(self, width, height):
        if not self.locked or self.misses >= ROI_FULL_FRAME_AFTER_MISSES:
            return None
        xs = [corner[0] for corner in self.corners]
        ys = [corner[1] for corner in self.corners]
        scale = min(width / 400.0, height / 240.0)
        margin = max(24.0 * scale,
                     self.long_side * ROI_MARGIN_RATIO)
        margin *= 1.0 + self.misses * 0.55
        x0 = int(clamp(min(xs) + self.velocity_x - margin, 0, width - 1))
        y0 = int(clamp(min(ys) + self.velocity_y - margin, 0, height - 1))
        x1 = int(clamp(max(xs) + self.velocity_x + margin, x0 + 1, width))
        y1 = int(clamp(max(ys) + self.velocity_y + margin, y0 + 1, height))
        roi = (x0, y0, x1 - x0, y1 - y0)
        if roi[2] * roi[3] > width * height * 0.82:
            return None
        return roi


class TargetDetector:
    def __init__(self):
        self.cvlite_active = (
            USE_CV_LITE and cv_lite is not None and
            hasattr(cv_lite, "grayscale_find_rectangles_with_corners"))
        self.shape = [DETECT_HEIGHT, DETECT_WIDTH]
        self.cvlite_errors = 0

    def name(self):
        return "CV-Lite" if self.cvlite_active else "find_blobs"

    def cvlite_candidates(self, img, tracker):
        width = img.width()
        height = img.height()
        self.shape[0] = height
        self.shape[1] = width
        rectangles = cv_lite.grayscale_find_rectangles_with_corners(
            self.shape, img.to_numpy_ref(),
            CVL_CANNY_LOW, CVL_CANNY_HIGH,
            CVL_APPROX_EPSILON, CVL_MIN_AREA_RATIO,
            CVL_MAX_ANGLE_COS, CVL_GAUSSIAN_SIZE)
        candidates = []
        if rectangles is None:
            return candidates
        for rect in rectangles:
            if len(rect) < 12:
                continue
            points = ((rect[4], rect[5]), (rect[6], rect[7]),
                      (rect[8], rect[9]), (rect[10], rect[11]))
            candidate = build_candidate(
                points, tracker, width, height, source_score=0.45)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def blob_candidates(self, img, tracker):
        width = img.width()
        height = img.height()
        frame_area = width * height
        pixels_threshold = max(24, int(frame_area * 0.00028))
        area_threshold = max(200, int(frame_area * MIN_FRAME_AREA_RATIO))
        roi = tracker.search_roi(width, height)
        if roi is None:
            blobs = img.find_blobs(
                [BLACK_THRESHOLD],
                pixels_threshold=pixels_threshold,
                area_threshold=area_threshold,
                x_stride=BLOB_X_STRIDE, y_stride=BLOB_Y_STRIDE,
                merge=False)
        else:
            blobs = img.find_blobs(
                [BLACK_THRESHOLD], roi=roi,
                pixels_threshold=pixels_threshold,
                area_threshold=area_threshold,
                x_stride=BLOB_X_STRIDE, y_stride=BLOB_Y_STRIDE,
                merge=False)
        candidates = []
        for blob in blobs:
            density = blob.density()
            solidity = blob.solidity()
            convexity = blob.convexity()
            if not (0.025 <= density <= 0.38):
                continue
            if not (0.02 <= solidity <= 0.52):
                continue
            if not (0.18 <= convexity <= 0.78):
                continue
            source_score = (
                max(0.0, 1.0 - abs(density - 0.15) / 0.25) +
                max(0.0, 1.0 - abs(solidity - 0.17) / 0.35) +
                max(0.0, 1.0 - abs(convexity - 0.42) / 0.45)) * 0.18
            candidate = build_candidate(
                blob.min_corners(), tracker, width, height, source_score)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def find_best(self, img, tracker):
        if self.cvlite_active:
            try:
                candidates = self.cvlite_candidates(img, tracker)
                self.cvlite_errors = 0
            except BaseException as error:
                self.cvlite_errors += 1
                if self.cvlite_errors >= CVL_MAX_CONSECUTIVE_ERRORS:
                    self.cvlite_active = False
                    print("CV-Lite disabled after repeated errors")
                else:
                    print("CV-Lite transient error %d/%d" %
                          (self.cvlite_errors,
                           CVL_MAX_CONSECUTIVE_ERRORS))
                sys.print_exception(error)
                candidates = self.blob_candidates(img, tracker)
        else:
            candidates = self.blob_candidates(img, tracker)

        candidates.sort(key=lambda item: item[C_SCORE], reverse=True)
        best = None
        best_score = -1.0
        limit = min(len(candidates), MAX_CANDIDATES_TO_VALIDATE)
        for index in range(limit):
            candidate = candidates[index]
            visual_score = appearance_score(img, candidate)
            if visual_score is None:
                continue
            score = candidate[C_SCORE] + visual_score * 1.7
            if score > best_score:
                values = list(candidate)
                values[C_SCORE] = score
                best = tuple(values)
                best_score = score
        return best


def map_to_display(value, input_size, output_size):
    if input_size <= 1:
        return 0
    mapped = round(value * (output_size - 1) / float(input_size - 1))
    return int(clamp(mapped, 0, output_size - 1))


def tracker_display_center(tracker, width, height):
    return (map_to_display(tracker.center_x, width, DISPLAY_WIDTH),
            map_to_display(tracker.center_y, height, DISPLAY_HEIGHT))


def coast_draw_color(misses):
    if MAX_COAST_DRAW_MISSES <= 1:
        return COLOR_COAST_END
    progress = clamp(
        (misses - 1) / float(MAX_COAST_DRAW_MISSES - 1), 0.0, 1.0)
    progress = progress * progress * (3.0 - 2.0 * progress)
    return (
        int(COLOR_COAST[0] +
            (COLOR_COAST_END[0] - COLOR_COAST[0]) * progress),
        int(COLOR_COAST[1] +
            (COLOR_COAST_END[1] - COLOR_COAST[1]) * progress),
        int(COLOR_COAST[2] +
            (COLOR_COAST_END[2] - COLOR_COAST[2]) * progress))


def draw_crosshair(img, x, y, color, size, thickness=2):
    img.draw_line((x - size, y, x + size, y),
                  color=color, thickness=thickness)
    img.draw_line((x, y - size, x, y + size),
                  color=color, thickness=thickness)


def draw_overlay(osd, tracker, width, height, fps_text):
    screen_x = DISPLAY_WIDTH // 2
    screen_y = DISPLAY_HEIGHT // 2
    target = None
    draw_crosshair(osd, screen_x, screen_y,
                   COLOR_SCREEN_CENTER, 11)

    if tracker.locked and tracker.misses <= MAX_COAST_DRAW_MISSES:
        color = (COLOR_LOCKED if tracker.measured else
                 coast_draw_color(tracker.misses))
        corners = []
        for point in tracker.corners:
            corners.append((
                map_to_display(point[0], width, DISPLAY_WIDTH),
                map_to_display(point[1], height, DISPLAY_HEIGHT)))
        for index in range(4):
            point1 = corners[index]
            point2 = corners[(index + 1) & 3]
            osd.draw_line((point1[0], point1[1], point2[0], point2[1]),
                          color=color, thickness=2)

        target_x, target_y = tracker_display_center(
            tracker, width, height)
        target = (target_x, target_y)
        link_color = COLOR_LINK if tracker.measured else color
        osd.draw_line((screen_x, screen_y, target_x, target_y),
                      color=link_color, thickness=2)
        draw_crosshair(osd, target_x, target_y, color, 9)
        osd.draw_rectangle((target_x - 4, target_y - 4, 9, 9),
                           color=color, thickness=1, fill=False)

    if target is None:
        coordinate_text = "CENTER: (--, --)"
    else:
        coordinate_text = "CENTER: (%d, %d)" % target
    status_text = "%s  %s" % (fps_text, coordinate_text)
    osd.draw_string_advanced(8, 8, 24, status_text, color=COLOR_TEXT)
    return target


def scale_to_u8(value, maximum):
    return int(clamp(round(value * 255.0 / (maximum - 1)), 0, 255))


def build_target_packet(display_x, display_y):
    target_x = int(clamp(round(display_x), 0, DISPLAY_WIDTH - 1))
    target_y = int(clamp(round(display_y), 0, DISPLAY_HEIGHT - 1))

    if UART_PACKET_MODE == "legacy_u8":
        aim_x = scale_to_u8(DISPLAY_WIDTH // 2, DISPLAY_WIDTH)
        aim_y = scale_to_u8(DISPLAY_HEIGHT // 2, DISPLAY_HEIGHT)
        scaled_x = scale_to_u8(target_x, DISPLAY_WIDTH)
        scaled_y = scale_to_u8(target_y, DISPLAY_HEIGHT)
        return bytearray([
            0x55, aim_x, 255 - aim_y, scaled_x, 255 - scaled_y])

    x_low = target_x & 0xFF
    x_high = (target_x >> 8) & 0xFF
    y_low = target_y & 0xFF
    y_high = (target_y >> 8) & 0xFF
    checksum = (0x55 + 0xAA + x_low + x_high + y_low + y_high) & 0xFF
    return bytearray([
        0x55, 0xAA, x_low, x_high, y_low, y_high, checksum])


def send_target(uart, display_x, display_y):
    if DZ_FRAME and uart is not None and _dz_tx(uart):      # dianzai 补丁：通道 1 target
        _dz.send(1, [("u8", 1), ("i16", int(display_x)), ("i16", int(display_y))])
        return
    if uart is not None:
        uart.write(build_target_packet(display_x, display_y))


def init_uart():
    if not UART_ENABLED:
        return None
    if UART_PACKET_MODE not in ("xy_u16", "legacy_u8"):
        raise ValueError("invalid UART_PACKET_MODE")
    fpioa = FPIOA()
    fpioa.set_function(UART_TX_PIN, FPIOA.UART2_TXD)
    fpioa.set_function(UART_RX_PIN, FPIOA.UART2_RXD)
    return UART(UART.UART2, UART_BAUDRATE)


def init_sensor():
    sensor = Sensor(fps=SENSOR_FPS)
    sensor.reset()
    sensor.set_framesize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT,
                         chn=CAM_CHN_ID_0)
    sensor.set_pixformat(Sensor.YUV420SP, chn=CAM_CHN_ID_0)
    sensor.set_framesize(width=DETECT_WIDTH, height=DETECT_HEIGHT,
                         chn=CAM_CHN_ID_2)
    sensor.set_pixformat(Sensor.GRAYSCALE, chn=CAM_CHN_ID_2)
    if SENSOR_HMIRROR:
        sensor.set_hmirror(True)
    if SENSOR_VFLIP:
        sensor.set_vflip(True)
    return sensor


def init_display(sensor):
    Display.bind_layer(
        **sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0),
        layer=Display.LAYER_VIDEO1)
    Display.init(Display.ST7701, to_ide=TO_IDE)


def main():
    sensor = None
    uart = None
    display_ready = False
    media_ready = False
    try:
        sensor = init_sensor()
        init_display(sensor)
        display_ready = True
        MediaManager.init()
        media_ready = True
        try:
            uart = init_uart()
        except BaseException as error:
            print("UART disabled; vision continues")
            sys.print_exception(error)
            uart = None
        osd = image.Image(DISPLAY_WIDTH, DISPLAY_HEIGHT, image.ARGB8888)
        sensor.run()

        clock = time.clock()
        detector = TargetDetector()
        tracker = TargetTracker()
        frame_id = 0
        fps_text = "FPS: --"
        print("detector=%s analysis=%dx%d" %
              (detector.name(), DETECT_WIDTH, DETECT_HEIGHT))
        print("uart2=%s tx=%d rx=%d mode=%s" %
              ("ON" if uart is not None else "OFF",
               UART_TX_PIN, UART_RX_PIN, UART_PACKET_MODE))

        while True:
            clock.tick()
            frame = sensor.snapshot(chn=CAM_CHN_ID_2)
            width = frame.width()
            height = frame.height()
            candidate = detector.find_best(frame, tracker)
            tracker.update(candidate, width, height)

            if frame_id % FPS_TEXT_UPDATE_FRAMES == 0:
                fps_text = "FPS: %.1f" % clock.fps()
            osd.clear()
            display_center = draw_overlay(
                osd, tracker, width, height, fps_text)
            Display.show_image(osd, 0, 0, Display.LAYER_OSD3)

            if (uart is not None and display_center is not None and
                    tracker.misses <= UART_SEND_COAST_MISSES and
                    frame_id % UART_SEND_EVERY_N_FRAMES == 0):
                send_target(uart, display_center[0], display_center[1])

            if frame_id % PRINT_INTERVAL == 0:
                if not tracker.locked:
                    state = "SEARCH"
                elif tracker.measured:
                    state = "LOCK"
                else:
                    state = "COAST"
                if display_center is None:
                    coordinate_text = "--,--"
                else:
                    coordinate_text = "%d,%d" % display_center
                print("%s,FPS=%.1f,CENTER=(%s),detector=%s" %
                      (state, clock.fps(), coordinate_text,
                       detector.name()))
            frame_id += 1
            if frame_id % GC_INTERVAL == 0:
                gc.collect()

    except KeyboardInterrupt as error:
        print("user stop:", error)
    except BaseException as error:
        sys.print_exception(error)
    finally:
        if sensor is not None:
            try:
                sensor.stop()
            except BaseException:
                pass
        if uart is not None:
            try:
                uart.deinit()
            except BaseException:
                pass
        if display_ready:
            Display.deinit()
            MediaManager.deinit()


if __name__ == "__main__":
    main()
