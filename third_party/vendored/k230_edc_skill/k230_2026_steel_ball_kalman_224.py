# Source: github.com/Loclove/Electronics-Design-Competition-Skill@cd46b72 assets/k230/k230-2026-steel-ball-kalman-224.py
# 上游原样搬入，仅加 dzframe 补丁（见同目录 SOURCE.md）。
# Lingmou 2026 电赛 steel-ball easter-egg template.
# Adapted from YaoYanbo's K230 high-speed steel-ball detector.
# Dedicated K230 high-speed steel-ball detector with a lightweight Kalman filter.
# It uses the GC2093 720p90 source mode and a low-bandwidth AI channel while
# using a 224x224 KPU model path for the fastest single-ball competition route.

from libs.PipeLine import PipeLine
from libs.YOLO import YOLO11
from libs.Utils import *
from media.sensor import *
from media.vencoder import *
from media.media import *
from media.display import *
import multimedia as mm
import network
import image
import _thread
import uctypes
import os
import time
import gc

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


# Export a matching 224x224 one-class kmodel for this path. If you only have the
# older 320x320 model, set KMODEL_PATH back to that file and use [320, 320].
KMODEL_PATH = "/sdcard/yolo11n_det_224.kmodel"
LABELS = {0: "steel ball"}
MODEL_INPUT_SIZE = [224, 224]
DISPLAY_SIZE = [800, 480]
RGB888P_SIZE = [224, 224]
CONFIDENCE_THRESHOLD = 0.60
NMS_THRESHOLD = 0.45
MAX_BOXES_NUM = 5

# Steel-ball post-filter and Kalman prediction. YOLO inference is unchanged.
BALL_CLASS_ID = 0
BALL_MIN_RADIUS = 4.0
BALL_MAX_RADIUS = 130.0
BALL_MIN_ROUNDNESS = 0.60
BALL_CONFIRM_FRAMES = 2
BALL_LOST_KEEP_FRAMES = 4
BALL_CONFIRM_GATE_PX = 180.0
BALL_BASE_GATE_PX = 110.0
BALL_PREDICTION_GATE_SCALE = 2.5
BALL_RADIUS_ALPHA = 0.22

# Constant-velocity Kalman parameters, expressed in pixels per AI frame.
KALMAN_MEASUREMENT_NOISE_PX = 3.5
KALMAN_ACCEL_NOISE_STILL = 1.2
KALMAN_ACCEL_NOISE_MOVING = 24.0
KALMAN_FULL_SPEED_PX = 70.0
KALMAN_STILL_SPEED_PX = 3.0
KALMAN_STILL_VELOCITY_DAMPING = 0.65
KALMAN_MISS_VELOCITY_DAMPING = 0.96
KALMAN_LOOKAHEAD_FRAMES = 0.70

# LCD-only hysteresis. Fast movement bypasses center smoothing completely.
UI_CENTER_DEADBAND_PX = 1.0
UI_RADIUS_DEADBAND_PX = 0.8
UI_CENTER_ALPHA_STILL = 0.35
UI_RADIUS_ALPHA = 0.18
UI_FULL_SPEED_PX = 8.0

SENSOR_ID = 2
SENSOR_SOURCE_SIZE = [1280, 720]
SENSOR_SOURCE_FPS = 90
DISPLAY_MODE = "st7701"
PRINT_YOLO_RESULTS = False
DRAW_BALL_LABEL = False
GC_INTERVAL_FRAMES = 60

# K230 AP and RTSP sender settings. Keep the encoder lightweight so the
# detector remains responsive when the AP has a connected client.
WIFI_SSID = "K230_VIDEO"
WIFI_PASSWORD = "05160037"
WIFI_AP_CHANNEL = 6
WIFI_START_RETRIES = 5
NETWORK_READY_UPTIME_MS = 2000
AP_READY_TIMEOUT_MS = 2000
WIFI_RETRY_DELAY_MS = 300
STARTUP_LOG_PATH = "/sdcard/k230_startup.log"

RTSP_SIZE = [400, 240]
RTSP_FPS = 30
RTSP_PORT = 8554
STREAM_NAME = "live"
DISPLAY_TYPE = Display.ST7701
DISPLAY_TO_IDE = False
RTSP_DISPLAY_CHN = CAM_CHN_ID_0
RTSP_SENSOR_CHN = CAM_CHN_ID_1
RTSP_VENC_CHN = VENC_CHN_ID_0


def safe_call(label, func, *args):
    try:
        func(*args)
    except Exception as exc:
        print("%s warning: %s" % (label, exc))


def startup_log(message, reset=False):
    try:
        mode = "w" if reset else "a"
        with open(STARTUP_LOG_PATH, mode) as log_file:
            log_file.write("%d %s\n" % (time.ticks_ms(), message))
    except Exception:
        pass


def bind_src(bind_info):
    try:
        return bind_info["src"]
    except Exception:
        return bind_info[0]


def new_sensor():
    try:
        return Sensor(
            id=SENSOR_ID,
            width=SENSOR_SOURCE_SIZE[0],
            height=SENSOR_SOURCE_SIZE[1],
            fps=SENSOR_SOURCE_FPS,
        )
    except TypeError:
        try:
            return Sensor(id=SENSOR_ID)
        except TypeError:
            return Sensor(SENSOR_ID)


def new_ap_wlan():
    try:
        return network.WLAN(network.AP_IF)
    except Exception:
        return network.WLAN(1)


def wait_for_network_ready():
    wait_ms = NETWORK_READY_UPTIME_MS - time.ticks_ms()
    if wait_ms > 0:
        print("Network startup wait: %dms" % wait_ms)
        startup_log("network startup wait %dms" % wait_ms)
        time.sleep_ms(wait_ms)


def start_wifi_ap(ssid, password, channel=WIFI_AP_CHANNEL):
    print("Starting K230 AP:", ssid)
    last_error = None

    for attempt in range(1, WIFI_START_RETRIES + 1):
        startup_log("AP attempt %d" % attempt)
        ap = new_ap_wlan()
        configured = False

        for mode in range(4):
            try:
                if mode == 0:
                    ap.config(ssid=ssid, key=password)
                elif mode == 1:
                    ap.config(ssid=ssid, key=password, channel=channel)
                elif mode == 2:
                    ap.config(essid=ssid, password=password)
                else:
                    ap.config("ssid", ssid)
                    ap.config("key", password)
                configured = True
                break
            except Exception as exc:
                last_error = exc

        if not configured:
            startup_log("AP config failed: %s" % last_error)
            time.sleep_ms(WIFI_RETRY_DELAY_MS)
            continue

        try:
            ap.active(True)
        except Exception as exc:
            print("AP active warning:", exc)
            startup_log("AP active warning: %s" % exc)

        ready_start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), ready_start) < AP_READY_TIMEOUT_MS:
            try:
                ip = ap.ifconfig()[0]
                if ip and ip != "0.0.0.0":
                    print("K230 AP active, IP:", ip)
                    print("RTSP URL: rtsp://%s:%d/%s" % (ip, RTSP_PORT, STREAM_NAME))
                    startup_log("AP ready IP %s" % ip)
                    return ap, ip
                last_error = "invalid IP %s" % ip
            except Exception as exc:
                last_error = exc
            time.sleep_ms(100)

        startup_log("AP attempt failed: %s" % last_error)
        time.sleep_ms(WIFI_RETRY_DELAY_MS)

    raise RuntimeError("AP start failed after retries: %s" % last_error)


class RtspRateMeter:
    def __init__(self):
        self.window_start = time.ticks_ms()
        self.frames = 0
        self.rate = 0.0

    def tick(self):
        self.frames += 1
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.window_start)
        if elapsed < 1000:
            return False
        self.rate = self.frames * 1000.0 / elapsed
        self.frames = 0
        self.window_start = now
        return True


class RateMeter:
    def __init__(self):
        self.window_start = time.ticks_ms()
        self.frames = 0
        self.rate = 0.0

    def tick(self):
        self.frames += 1
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.window_start)
        if elapsed >= 1000:
            self.rate = self.frames * 1000.0 / elapsed
            self.frames = 0
            self.window_start = now
        return self.rate


class KalmanAxis:
    def __init__(self):
        self.position = 0.0
        self.velocity = 0.0
        self.p00 = 25.0
        self.p01 = 0.0
        self.p10 = 0.0
        self.p11 = 400.0

    def reset(self, position, velocity=0.0):
        self.position = float(position)
        self.velocity = float(velocity)
        self.p00 = 25.0
        self.p01 = 0.0
        self.p10 = 0.0
        self.p11 = 400.0

    def predict(self, acceleration_noise):
        self.position += self.velocity

        accel_variance = acceleration_noise * acceleration_noise
        q00 = accel_variance * 0.25
        q01 = accel_variance * 0.50
        q11 = accel_variance

        p00 = self.p00
        p01 = self.p01
        p10 = self.p10
        p11 = self.p11
        self.p00 = p00 + p01 + p10 + p11 + q00
        self.p01 = p01 + p11 + q01
        self.p10 = p10 + p11 + q01
        self.p11 = p11 + q11

    def correct(self, measurement, measurement_noise):
        measurement_variance = measurement_noise * measurement_noise
        innovation = float(measurement) - self.position
        innovation_variance = self.p00 + measurement_variance
        if innovation_variance <= 0.000001:
            return

        p00 = self.p00
        p01 = self.p01
        p10 = self.p10
        p11 = self.p11
        gain_position = p00 / innovation_variance
        gain_velocity = p10 / innovation_variance

        self.position += gain_position * innovation
        self.velocity += gain_velocity * innovation

        new_p00 = (1.0 - gain_position) * p00
        new_p01 = (1.0 - gain_position) * p01
        new_p10 = p10 - gain_velocity * p00
        new_p11 = p11 - gain_velocity * p01
        cross_covariance = (new_p01 + new_p10) * 0.5
        self.p00 = max(0.0001, new_p00)
        self.p01 = cross_covariance
        self.p10 = cross_covariance
        self.p11 = max(0.0001, new_p11)


class OverlaySmoother:
    def __init__(self):
        self.x = None
        self.y = None
        self.radius = None

    def update(self, ball):
        if ball is None:
            self.x = None
            self.y = None
            self.radius = None
            return None

        target_x = ball["x"]
        target_y = ball["y"]
        target_radius = ball["radius"]
        speed = ball["speed"]

        if self.x is None:
            self.x = target_x
            self.y = target_y
            self.radius = target_radius
        else:
            dx = target_x - self.x
            dy = target_y - self.y
            distance = (dx * dx + dy * dy) ** 0.5

            if ball["lost"] > 0 or speed >= UI_FULL_SPEED_PX:
                center_alpha = 1.0
            elif distance <= UI_CENTER_DEADBAND_PX:
                center_alpha = 0.0
            else:
                speed_ratio = min(speed / UI_FULL_SPEED_PX, 1.0)
                center_alpha = UI_CENTER_ALPHA_STILL + (
                    1.0 - UI_CENTER_ALPHA_STILL
                ) * speed_ratio

            self.x += dx * center_alpha
            self.y += dy * center_alpha

            radius_delta = target_radius - self.radius
            if abs(radius_delta) > UI_RADIUS_DEADBAND_PX:
                self.radius += radius_delta * UI_RADIUS_ALPHA

        return {
            "x": self.x,
            "y": self.y,
            "radius": self.radius,
        }


class StableBallTracker:
    def __init__(self):
        self.active = False
        self.radius = 0.0
        self.score = 0.0
        self.lost = 0
        self.pending = None
        self.pending_count = 0
        self.kalman_x = KalmanAxis()
        self.kalman_y = KalmanAxis()

    def update(self, result):
        if self.active:
            self._predict()

        candidates = self._parse_candidates(result)
        candidate = self._select_candidate(candidates)

        if candidate is None:
            return self._handle_miss()

        if not self.active:
            return self._confirm_new_target(candidate)

        self.lost = 0
        measurement_noise = KALMAN_MEASUREMENT_NOISE_PX * (
            1.4 - min(1.0, candidate["score"]) * 0.4
        )
        self.kalman_x.correct(candidate["x"], measurement_noise)
        self.kalman_y.correct(candidate["y"], measurement_noise)

        speed = self._speed()
        if speed < KALMAN_STILL_SPEED_PX:
            self.kalman_x.velocity *= KALMAN_STILL_VELOCITY_DAMPING
            self.kalman_y.velocity *= KALMAN_STILL_VELOCITY_DAMPING

        self.radius += (candidate["radius"] - self.radius) * BALL_RADIUS_ALPHA
        self.score = candidate["score"]
        return self._current_ball()

    def _predict(self):
        speed_ratio = min(self._speed() / KALMAN_FULL_SPEED_PX, 1.0)
        acceleration_noise = KALMAN_ACCEL_NOISE_STILL + (
            KALMAN_ACCEL_NOISE_MOVING - KALMAN_ACCEL_NOISE_STILL
        ) * speed_ratio
        self.kalman_x.predict(acceleration_noise)
        self.kalman_y.predict(acceleration_noise)

    def _speed(self):
        vx = self.kalman_x.velocity
        vy = self.kalman_y.velocity
        return (vx * vx + vy * vy) ** 0.5

    def _parse_candidates(self, result):
        candidates = []
        try:
            boxes = result[0]
            class_ids = result[1]
            scores = result[2]
            count = min(len(boxes), len(class_ids), len(scores))
        except Exception:
            return candidates

        for index in range(count):
            try:
                class_id = int(class_ids[index])
                score = float(scores[index])
                box = boxes[index]
                x = float(box[0])
                y = float(box[1])
                width = float(box[2])
                height = float(box[3])
            except Exception:
                continue

            if class_id != BALL_CLASS_ID or width <= 1.0 or height <= 1.0:
                continue

            short_side = min(width, height)
            long_side = max(width, height)
            roundness = short_side / long_side
            radius = short_side * 0.48
            if roundness < BALL_MIN_ROUNDNESS:
                continue
            if radius < BALL_MIN_RADIUS or radius > BALL_MAX_RADIUS:
                continue

            candidates.append({
                "x": x + width * 0.5,
                "y": y + height * 0.5,
                "radius": radius,
                "score": score,
                "roundness": roundness,
            })

        return candidates

    def _select_candidate(self, candidates):
        if not candidates:
            return None

        best = None
        best_rank = -1000000.0
        for candidate in candidates:
            rank = candidate["score"] * 100.0 + candidate["roundness"] * 12.0
            if self.active:
                dx = candidate["x"] - self.kalman_x.position
                dy = candidate["y"] - self.kalman_y.position
                distance = (dx * dx + dy * dy) ** 0.5
                speed = self._speed()
                gate = max(
                    BALL_BASE_GATE_PX,
                    self.radius * 5.0,
                    40.0 + speed * BALL_PREDICTION_GATE_SCALE,
                )
                gate *= 1.0 + self.lost * 0.45
                if distance > gate:
                    continue
                rank -= distance * 0.18
                rank -= abs(candidate["radius"] - self.radius) * 0.25

            if best is None or rank > best_rank:
                best = candidate
                best_rank = rank

        return best

    def _confirm_new_target(self, candidate):
        if self.pending is None:
            self.pending = candidate
            self.pending_count = 1
            return None

        dx = candidate["x"] - self.pending["x"]
        dy = candidate["y"] - self.pending["y"]
        distance = (dx * dx + dy * dy) ** 0.5
        confirm_gate = max(BALL_CONFIRM_GATE_PX, candidate["radius"] * 5.0)
        if distance <= confirm_gate:
            self.pending = candidate
            self.pending_count += 1
        else:
            self.pending = candidate
            self.pending_count = 1

        if self.pending_count < BALL_CONFIRM_FRAMES:
            return None

        self.active = True
        self.radius = candidate["radius"]
        self.score = candidate["score"]
        self.lost = 0
        self.kalman_x.reset(candidate["x"], dx)
        self.kalman_y.reset(candidate["y"], dy)
        self.pending = None
        self.pending_count = 0
        return self._current_ball()

    def _handle_miss(self):
        self.pending = None
        self.pending_count = 0
        if not self.active:
            return None

        self.lost += 1
        if self.lost <= BALL_LOST_KEEP_FRAMES:
            self.kalman_x.velocity *= KALMAN_MISS_VELOCITY_DAMPING
            self.kalman_y.velocity *= KALMAN_MISS_VELOCITY_DAMPING
            return self._current_ball()

        self.active = False
        return None

    def _current_ball(self):
        lookahead = KALMAN_LOOKAHEAD_FRAMES if self.lost == 0 else 0.0
        display_x = self.kalman_x.position + self.kalman_x.velocity * lookahead
        display_y = self.kalman_y.position + self.kalman_y.velocity * lookahead
        return {
            "x": max(0.0, min(DISPLAY_SIZE[0] - 1.0, display_x)),
            "y": max(0.0, min(DISPLAY_SIZE[1] - 1.0, display_y)),
            "radius": self.radius,
            "score": self.score,
            "lost": self.lost,
            "speed": self._speed(),
        }


class DedicatedBallYolo:
    def __init__(self):
        self.sensor = None
        self.yolo = None
        self.encoder = None
        self.link = None
        self.osd_img = None
        self.rtspserver = mm.rtsp_server()
        self.ai_meter = RateMeter()
        self.ai_fps = 0.0
        self.fps_text = "AI 0.0"
        self.stream_meter = RtspRateMeter()
        self.frame_count = 0
        self.use_fast_text = None
        self.ball_tracker = StableBallTracker()
        self.overlay_smoother = OverlaySmoother()
        self.display_inited = False
        self.media_inited = False
        self.encoder_created = False
        self.encoder_started = False
        self.sensor_running = False
        self.rtsp_started = False
        self.rtsp_thread_running = False
        self.rtsp_thread_done = True
        self.first_stream_frame = False

    def start(self):
        self._init_camera_display_encoder()
        self._init_rtsp_server()

        self.yolo = YOLO11(
            task_type="detect",
            mode="video",
            kmodel_path=KMODEL_PATH,
            labels=LABELS,
            rgb888p_size=RGB888P_SIZE,
            model_input_size=MODEL_INPUT_SIZE,
            display_size=DISPLAY_SIZE,
            conf_thresh=CONFIDENCE_THRESHOLD,
            nms_thresh=NMS_THRESHOLD,
            max_boxes_num=MAX_BOXES_NUM,
            debug_mode=0,
        )
        self.yolo.config_preprocess()
        self.encoder.Start(RTSP_VENC_CHN)
        self.encoder_started = True
        self.sensor.run()
        self.sensor_running = True

        self.rtsp_thread_running = True
        self.rtsp_thread_done = False
        _thread.start_new_thread(self._rtsp_worker, ())

        print("Turbo single-ball YOLO + RTSP active on LCD.")
        print("CH0 LCD 800x480; CH1 RTSP 400x240@30; CH2 YOLO 320x192.")
        print("Sensor source requested: 1280x720@90.")

    def _init_camera_display_encoder(self):
        self.sensor = new_sensor()
        self.sensor.reset()

        Display.init(
            DISPLAY_TYPE,
            width=DISPLAY_SIZE[0],
            height=DISPLAY_SIZE[1],
            osd_num=1,
            to_ide=DISPLAY_TO_IDE,
        )
        self.display_inited = True

        self.sensor.set_framesize(
            width=DISPLAY_SIZE[0],
            height=DISPLAY_SIZE[1],
            chn=RTSP_DISPLAY_CHN,
        )
        self.sensor.set_pixformat(Sensor.YUV420SP, chn=RTSP_DISPLAY_CHN)

        self.sensor.set_framesize(
            width=RTSP_SIZE[0],
            height=RTSP_SIZE[1],
            chn=RTSP_SENSOR_CHN,
            alignment=12,
        )
        self.sensor.set_pixformat(Sensor.YUV420SP, chn=RTSP_SENSOR_CHN)
        try:
            self.sensor._set_chn_fps(chn=RTSP_SENSOR_CHN, fps=RTSP_FPS)
            print("RTSP fps set to", RTSP_FPS)
        except Exception as exc:
            print("RTSP fps warning:", exc)

        self.sensor.set_framesize(
            width=RGB888P_SIZE[0],
            height=RGB888P_SIZE[1],
            chn=CAM_CHN_ID_2,
        )
        self.sensor.set_pixformat(Sensor.RGBP888, chn=CAM_CHN_ID_2)

        display_bind = self.sensor.bind_info(x=0, y=0, chn=RTSP_DISPLAY_CHN)
        Display.bind_layer(**display_bind, layer=Display.LAYER_VIDEO1)
        self.osd_img = image.Image(DISPLAY_SIZE[0], DISPLAY_SIZE[1], image.ARGB8888)

        self.encoder = Encoder()
        self.encoder.SetOutBufs(
            RTSP_VENC_CHN,
            8,
            RTSP_SIZE[0],
            RTSP_SIZE[1],
        )
        chn_attr = ChnAttrStr(
            self.encoder.PAYLOAD_TYPE_H264,
            self.encoder.H264_PROFILE_MAIN,
            RTSP_SIZE[0],
            RTSP_SIZE[1],
        )
        self.encoder.Create(RTSP_VENC_CHN, chn_attr)
        self.encoder_created = True

        encode_bind = self.sensor.bind_info(chn=RTSP_SENSOR_CHN)
        self.link = MediaManager.link(
            bind_src(encode_bind),
            (VIDEO_ENCODE_MOD_ID, VENC_DEV_ID, RTSP_VENC_CHN),
        )
        MediaManager.init()
        self.media_inited = True

    def _init_rtsp_server(self):
        self.rtspserver.rtspserver_init(RTSP_PORT)
        self.rtspserver.rtspserver_createsession(
            STREAM_NAME,
            mm.multi_media_type.media_h264,
            False,
        )
        self.rtspserver.rtspserver_start()
        self.rtsp_started = True

    def _rtsp_worker(self):
        stream_data = StreamData()
        try:
            while self.rtsp_thread_running:
                ret = self.encoder.GetStream(RTSP_VENC_CHN, stream_data, 1000)
                if ret != 0:
                    continue

                try:
                    for pack_idx in range(stream_data.pack_cnt):
                        data = bytes(
                            uctypes.bytearray_at(
                                stream_data.data[pack_idx],
                                stream_data.data_size[pack_idx],
                            )
                        )
                        self.rtspserver.rtspserver_sendvideodata(
                            STREAM_NAME,
                            data,
                            stream_data.data_size[pack_idx],
                            1000,
                        )
                finally:
                    self.encoder.ReleaseStream(RTSP_VENC_CHN, stream_data)

                if self.stream_meter.tick():
                    print(
                        "FPS AI=%.1f RTSP=%.1f"
                        % (self.ai_fps, self.stream_meter.rate)
                    )

                if not self.first_stream_frame:
                    print("RTSP first encoded frame ready")
                    self.first_stream_frame = True
        except BaseException as exc:
            if self.rtsp_thread_running:
                print("RTSP worker warning:", exc)
        finally:
            self.rtsp_thread_done = True

    def run_forever(self):
        while True:
            os.exitpoint()

            frame = self.sensor.snapshot(chn=CAM_CHN_ID_2)
            result = self.yolo.run(frame.to_numpy_ref())
            ball = self.ball_tracker.update(result)
            if DZ_FRAME and _dz_tx():                                  # dianzai 补丁：通道 2 ball
                _dz.send(2, [("u8", (1 | (2 if ball["lost"] else 0)) if ball else 0), ("i16", int(ball["x"]) if ball else 0),
                             ("i16", int(ball["y"]) if ball else 0), ("u16", int(ball["radius"]) if ball else 0)])
            self.osd_img.clear()
            self._draw_ball_overlay(ball)

            previous_fps = self.ai_fps
            self.ai_fps = self.ai_meter.tick()
            if self.ai_fps != previous_fps:
                self.fps_text = "AI %.1f" % self.ai_fps
            self._draw_fps()
            Display.show_image(self.osd_img, 0, 0, Display.LAYER_OSD3)

            if PRINT_YOLO_RESULTS:
                print(result)

            self.frame_count += 1
            if self.frame_count >= GC_INTERVAL_FRAMES:
                gc.collect()
                self.frame_count = 0

    def stop(self):
        self.rtsp_thread_running = False
        wait_start = time.ticks_ms()
        while not self.rtsp_thread_done:
            if time.ticks_diff(time.ticks_ms(), wait_start) > 1200:
                print("RTSP thread stop timeout")
                break
            time.sleep_ms(10)

        if self.yolo:
            try:
                self.yolo.deinit()
            except Exception as exc:
                print("yolo.deinit warning:", exc)
            self.yolo = None

        if self.sensor_running and self.sensor:
            safe_call("sensor.stop", self.sensor.stop)
            self.sensor_running = False

        if self.display_inited:
            safe_call("Display.deinit", Display.deinit)
            self.display_inited = False

        if self.link:
            safe_call("link.destroy", self.link.destroy)
            self.link = None

        if self.encoder:
            if self.encoder_started:
                safe_call("Encoder.Stop", self.encoder.Stop, RTSP_VENC_CHN)
                self.encoder_started = False
            if self.encoder_created:
                safe_call("Encoder.Destroy", self.encoder.Destroy, RTSP_VENC_CHN)
                self.encoder_created = False
            self.encoder = None

        if self.rtsp_started:
            safe_call("rtspserver_stop", self.rtspserver.rtspserver_stop)
            self.rtsp_started = False
        safe_call("rtspserver_deinit", self.rtspserver.rtspserver_deinit)

        if self.media_inited:
            safe_call("MediaManager.deinit", MediaManager.deinit)
            self.media_inited = False
        gc.collect()

    def _draw_ball_overlay(self, ball):
        osd_img = self.osd_img
        overlay_ball = self.overlay_smoother.update(ball)
        if overlay_ball is None:
            return

        center_x = int(round(overlay_ball["x"]))
        center_y = int(round(overlay_ball["y"]))
        radius = max(3, int(round(overlay_ball["radius"])))

        try:
            osd_img.draw_circle(
                center_x,
                center_y,
                radius,
                color=(0, 255, 0),
                thickness=3,
                fill=False,
            )
            osd_img.draw_circle(
                center_x,
                center_y,
                2,
                color=(255, 0, 0),
                thickness=1,
                fill=True,
            )
        except Exception:
            pass

        if DRAW_BALL_LABEL:
            label_x = max(4, min(center_x - radius, DISPLAY_SIZE[0] - 190))
            label_y = max(28, center_y - radius - 24)
            label = "BALL %.2f  (%d,%d)" % (ball["score"], center_x, center_y)
            try:
                osd_img.draw_string_advanced(
                    label_x,
                    label_y,
                    18,
                    label,
                    color=(0, 255, 0),
                )
            except Exception:
                pass

    def _draw_fps(self):
        osd_img = self.osd_img
        text = "AI %.1f  RTSP %.1f" % (self.ai_fps, self.stream_meter.rate)
        if self.use_fast_text is not False:
            try:
                osd_img.draw_string(
                    4,
                    4,
                    text,
                    color=(255, 255, 255),
                    scale=2,
                )
                self.use_fast_text = True
                return
            except Exception:
                self.use_fast_text = False

        try:
            osd_img.draw_string_advanced(
                4,
                4,
                20,
                text,
                color=(255, 255, 255, 255),
            )
        except Exception:
            try:
                osd_img.draw_string_advanced(
                    4,
                    4,
                    20,
                    text,
                    color=(255, 255, 255),
                )
            except Exception:
                pass


def main():
    os.exitpoint(os.EXITPOINT_ENABLE)
    startup_log("combined YOLO+RTSP main.py boot start", reset=True)
    wait_for_network_ready()

    wifi_ap = None
    app = None
    try:
        wifi_ap, ip = start_wifi_ap(WIFI_SSID, WIFI_PASSWORD)
        app = DedicatedBallYolo()
        app.start()
        startup_log("combined YOLO+RTSP application started, IP %s" % ip)
        app.run_forever()
    except KeyboardInterrupt:
        print("Stopping...")
    except BaseException as exc:
        if "IDE interrupt" in str(exc):
            print("Stopping...")
        else:
            print("Fatal startup/runtime error:", exc)
    finally:
        if app:
            app.stop()
        if wifi_ap:
            safe_call("AP deactive", wifi_ap.active, False)
        print("Stopped")


main()
