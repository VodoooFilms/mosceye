"""A fixture must loop past the last decodable frame without camera failure."""
import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
import cv2,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera import FrameSource

class EndOfVideo:
    def __init__(self):self.seeks=[];self.sec=0
    def isOpened(self):return True
    def get(self,key):return 13.093 if key==cv2.CAP_PROP_FPS else 1454
    def set(self,key,value):self.sec=value/1000;self.seeks.append(self.sec)
    def read(self):return (False,None) if self.sec>110.8 else (True,np.full((16,16,3),100,np.uint8))
    def release(self):pass

class VideoLoopTests(unittest.TestCase):
    def test_duration_after_last_decodable_frame_wraps_to_zero(self):
        cap=EndOfVideo();source=FrameSource('fixture.mp4');source.position=110.9
        with patch('camera.cv2.VideoCapture',return_value=cap):
            source.start()
            try:
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    try:frame=source.latest();break
                    except RuntimeError:time.sleep(.01)
                else:self.fail('The producer remained stuck at EOF')
                self.assertIn(0,cap.seeks)
                self.assertEqual(frame.sec,0)
                self.assertIsNone(source.status()['camera_error'])
            finally:source.close()
