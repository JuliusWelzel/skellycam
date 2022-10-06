import logging
import threading
import time
import traceback

import cv2
import numpy as np

from fast_camera_capture.detection.models.frame_payload import FramePayload
from fast_camera_capture.opencv.camera.models.cam_args import CamArgs
from fast_camera_capture.opencv.config.apply_config import apply_configuration
from fast_camera_capture.opencv.config.determine_backend import determine_backend

logger = logging.getLogger(__name__)


class VideoCaptureThread(threading.Thread):
    def __init__(
        self,
        config: CamArgs
    ):
        super().__init__()
        self._new_frame_ready = False
        self.daemon = True

        self._config = config
        self._is_capturing_frames = False
        self._is_recording_frames = False

        self._number_of_frames_recorded: int = 0
        self._num_frames_processed = 0

        self._elapsed_during_frame_grab = []
        self._capture_timestamps = []
        self._median_framerate = None
        self._frame: FramePayload = FramePayload()
        self._cv2_video_capture = self._create_cv2_capture()

    @property
    def first_frame_timestamp(self):
        if len(self._capture_timestamps) > 0:
            return self._capture_timestamps[0]
        return None

    @property
    def median_framerate(self):
        if self._num_frames_processed == 0:
            logger.warning(
                f"No Frames processed yet, cannot calculate median_framerate"
            )
        else:
            self._median_framerate = np.nanmedian(
                (np.diff(self._capture_timestamps) ** -1) / 1e9
            )

        return self._median_framerate

    @property
    def latest_frame_number(self):
        return self._number_of_frames_recorded

    @property
    def latest_frame(self) -> FramePayload:
        self._new_frame_ready = False
        return self._frame

    @property
    def new_frame_ready(self):
        return self._new_frame_ready

    @property
    def is_capturing_frames(self) -> bool:
        """Is the thread capturing frames from the cameras (but not necessarily recording them, that's handled by `is_recording_frames`)"""
        return self._is_capturing_frames

    def run(self):
        self._start_frame_loop()

    def _start_frame_loop(self):
        self._is_capturing_frames = True
        logger.info(f"Camera ID: [{self._config.cam_id}] Frame capture loop has started")
        self._capture_start_timestamp_ns = time.time_ns()
        try:
            while self._is_capturing_frames:
                self._frame = self._get_next_frame()
                self._capture_timestamps.append(
                    self._capture_start_timestamp_ns
                )
                self._num_frames_processed += 1
        except:
            logger.error(f"Camera ID: [{self._config.cam_id}] Frame loop thread exited due to error")
            traceback.print_exc()
        else:
            logger.info(f"Camera ID: [{self._config.cam_id}] Frame capture has stopped.")

    def _create_cv2_capture(self):
        logger.info(f"Connecting to Camera: {self._config.cam_id}...")
        cap_backend = determine_backend()

        try:
            self._cv2_video_capture.release()
        except:
            pass

        capture = cv2.VideoCapture(
            int(self._config.cam_id), cap_backend
        )

        try:
            success, image = capture.read()
        except Exception as e:
            logger.error(
                f"Problem when trying to read frame from Camera: {self._config.cam_id}"
            )
            traceback.print_exc()
            raise e

        if not success or image is None:
            logger.error(
                f"Failed to read frame from camera at port# {self._config.cam_id}: "
                f"returned value: {success}, "
                f"returned image: {image}"
            )
            raise Exception

        apply_configuration(capture, self._config)

        logger.info(f"Successfully connected to Camera: {self._config.cam_id}!")
        return capture

    def _get_next_frame(self):
        try:
            self._cv2_video_capture.grab()
            success, image = self._cv2_video_capture.retrieve()
            retrieval_timestamp = time.perf_counter_ns()
            if not self.first_frame_timestamp:
                current_frame_timestamp_diff = retrieval_timestamp
            else:
                current_frame_timestamp_diff = (
                    retrieval_timestamp - self.first_frame_timestamp
                )
        except:
            logger.error(f"Failed to read frame from Camera: {self._config.cam_id}")
            raise Exception

        self._new_frame_ready = success

        if success:
            self._number_of_frames_recorded += 1

        return FramePayload(
            success=success,
            image=image,
            timestamp_unix_time_seconds=retrieval_timestamp,
            timestamp_in_seconds_from_record_start=current_frame_timestamp_diff,
            frame_number=self.latest_frame_number,
            webcam_id=str(self._config.cam_id),
        )

    def stop(self):
        self._is_capturing_frames = False
        if self._cv2_video_capture is not None:
            logger.debug(
                f"Releasing `opencv_video_capture_object` for Camera: {self._config.cam_id}"
            )
            self._cv2_video_capture.release()