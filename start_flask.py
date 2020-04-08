# ###################################################################
# Ruben Cardenes -- Apr 2020
#
# File:        start.py
# Description: This scripts starts a web app in the a machine for video surveillance
#              Users can connect to the video streaming using a web browser.
#
# ###################################################################

import time
import numpy as np
import os
import cv2
from threading import Thread
import threading
from argparse import ArgumentParser
from MultiObjectMotionDetection import MultiObjectMotionDetector
from flask import Response
from flask import Flask
from flask import render_template
from create_video import make_video


class MemorySharing():

    def __init__(self):
        self.frame = None

    def generate_frames(self):
        while True:
            with lock:
                if self.frame is None:
                    continue
                (flag, encodedImage) = cv2.imencode(".jpg", self.frame)

                # ensure the frame was successfully encoded
                if not flag:
                    continue

                # Add header to frame in byte format
                bytes_to_send = (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' +
                                 bytearray(encodedImage) + b'\r\n')

            yield bytes_to_send


# Video Sending Thread
class VideoSendThread(Thread):
    # A class to send video frames using threads
    # This class inherits from Thread, which means that will run on a separate Thread
    # whenever called, it starts the run method

    def __init__(self, container, camera_resolution=(640, 480), camera_type="USB"):
        Thread.__init__(self)
        # create socket and bind host
        self.camera_resolution = camera_resolution
        self.stopped = False
        self.md = MultiObjectMotionDetector()
        self.output_name = ""
        self.save_time = 0
        self.container = container
        self.vid = None
        self.camera_type = camera_type

    def save_frame(self, frame):
        date_time = time.strftime("%m_%d_%Y-%H:%M:%S")
        self.output_name = os.path.join("./static/images", date_time + ".jpg")
        self.save_time = time.time()
        cv2.imwrite(self.output_name, frame)
        cv2.putText(frame, "Saving frame", (0, 10), cv2.FONT_HERSHEY_DUPLEX, 0.5, (0, 0, 255), 1)

    def run_motion_detection(self, frame):
        # MOTION DETECTION
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_blur = cv2.GaussianBlur(gray, (7, 7), 0)
        self.md.update(gray_blur)
        thresh = np.zeros(frame.shape)
        thresh, md_boxes = self.md.detect(gray_blur)
        if md_boxes is not None:
            total_area = 0
            for b in md_boxes:
                cv2.rectangle(frame, (b[0], b[1]), (b[2], b[3]),
                              (0, 0, 255), 1)
                total_area += (b[2] - b[0]) * (b[3] - b[1])
            if total_area > 500:
                # print("boxes: ", md_boxes)
                if time.time() - self.save_time > 3:
                    self.save_frame(frame)

    def run_pi_camera(self):
        print("Running PI camera")
        from picamera.array import PiRGBArray
        from picamera import PiCamera
        try:
            with PiCamera() as camera:
                camera.resolution = self.camera_resolution  # pi camera resolution
                camera.framerate = 10  # 10 frames/sec
                time.sleep(2)  # give 2 secs for camera to initialize
                rawCapture = PiRGBArray(camera, size=self.camera_resolution)
                stream = camera.capture_continuous(rawCapture,
                                                   format="bgr", use_video_port=True)

                # send jpeg format video stream
                for f in stream:
                    frame = f.array
                    rawCapture.truncate(0)

                    # MOTION DETECTION
                    self.run_motion_detection(frame)

                    with lock:
                        self.container.frame = frame

        finally:
            self.stopped = True

    def run_usb_camera(self):
        print("Running USB camera ")
        self.vid = cv2.VideoCapture(0)
        try:
            while True:
                ret, frame = self.vid.read()
                if not ret:
                    continue

                # MOTION DETECTION
                self.run_motion_detection(frame)

                with lock:
                    self.container.frame = frame

        finally:
            self.stopped = True

    def run(self):
        if self.camera_type == "USB":
            self.run_usb_camera()
        else:
            self.run_pi_camera()


app = Flask(__name__)
lock = threading.Lock()
container = MemorySharing()


@app.route("/")
def index():
    # return the rendered template
    return render_template("index.html")


@app.route("/summary")
def summary():
    imgs = ["images/" + file for file in os.listdir('static/images')]
    imgs.sort()
    print(imgs)
    # return the rendered template
    return render_template("summary.html", imgs=imgs)


@app.route("/make_summary")
def make_summary():
    day = time.strftime("%m_%d_%Y")
    imgs = ["static/images/" + file for file in os.listdir('static/images') if day in file]
    imgs.sort()
    make_video(imgs, f"static/video_summary/{day}.mp4")
    # return the rendered template
    return render_template("video_summary.html")


@app.route("/video_summary")
def video_summary():
    vids = ["video_summary/" + file for file in os.listdir('static/video_summary')]
    vids.sort()
    # return the rendered template
    return render_template("video_summary.html", vids=vids)


@app.route("/video_feed")
def video_feed():
    # return the response generated along with the specific media
    # type (mime type)
    return Response(container.generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route('/do_progress')
def do_progress():
    return render_template('progress.html')


@app.route('/progress')
def progress():
    def generate():
        x = 0

        while x <= 100:
            yield "data:" + str(x) + "\n\n"
            x = x + 10
            time.sleep(0.5)

    return Response(generate(), mimetype='text/event-stream')


if __name__ == "__main__":

    parser = ArgumentParser()
    parser.add_argument('--port', type=int,
                        dest='port',
                        default=8887,
                        help='socket port',
                        required=False)
    parser.add_argument('--host', type=str,
                        dest='host',
                        default='0.0.0.0',
                        help='destination host name or ip',
                        required=False)
    parser.add_argument('-p', type=str,
                        dest='camera_type',
                        default='USB',
                        help='use piCamera',
                        required=False)
    args = vars(parser.parse_args())

    host = args['host']
    port = args['port']

    threads = []

    newthread = VideoSendThread(container, camera_type=args['camera_type'])
    newthread.start()
    threads.append(newthread)

    # initialize a flask object
    app.run(host=args["host"], port=args["port"], debug=True,
            threaded=True, use_reloader=False)

    for t in threads:
        t.join()
