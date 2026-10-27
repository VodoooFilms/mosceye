"""Restart behaviour: keep the last good result, but never present it as fresh."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sam_service
from sam_service import Engine
from camera import Frame,timestamp


class Source:
    def __init__(self):
        image=np.zeros((720,1270,3),np.uint8)
        self.frame=Frame('frame-1',image,b'jpg',timestamp(),'footage',1,8.)
    def latest(self,frame_id=None):return self.frame
    def status(self):return dict(source_version=1,playing=True)


class Vision:
    device='cpu';sam=None;sam_error=None


class RestoreTests(unittest.TestCase):
    def test_last_result_is_restored_and_marked_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);state=tmp/'mosceye_status.json';caja=tmp/'caja_status.json';cfg=tmp/'camera_config.json'
            state.write_text(json.dumps(dict(schema_version=2,counts_ready=True,people_in_queue=3,
                people_in_store=9,cashier_present=True,cashier_count=1,store_calibrated=True,
                zones_calibrated=True,captured_at=timestamp(),captured_epoch=1.0,timestamp=timestamp(),
                frame_id='frame-old',detections=[],masks=[],masks_total=0,inference_ms=10,
                detector_ms=9,sam_ms=None,frame_w=1270,frame_h=720,detector='d',model='m',
                total_ms=20,people=9,frame_time_sec=5.0,source='footage',config_version=1,
                empty_minutes=None)),encoding='utf-8')
            with patch.object(sam_service,'STATE_PATH',state),patch.object(sam_service,'CAJA_PATH',caja),patch.object(sam_service,'CONFIG_PATH',cfg):
                engine=Engine(Vision(),Source(),publish=True)
                snapshot=engine.snapshot()
                self.assertTrue(snapshot['stale']);self.assertFalse(snapshot['ready'])
                self.assertTrue(snapshot['counts_ready']);self.assertEqual(snapshot['people_in_store'],9)
                self.assertEqual(snapshot['frame_id'],'frame-old')
                engine._publish()
                payload=json.loads(caja.read_text(encoding='utf-8'))
                self.assertTrue(payload['stale']);self.assertEqual(payload['people_in_store'],9)
                self.assertEqual(payload['people_in_queue'],3)

    def test_old_state_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);state=tmp/'mosceye_status.json';cfg=tmp/'camera_config.json'
            state.write_text(json.dumps(dict(schema_version=2,counts_ready=True,people_in_store=9)),encoding='utf-8')
            old=1_000_000
            import os;os.utime(state,(old,old))
            with patch.object(sam_service,'STATE_PATH',state),patch.object(sam_service,'CAJA_PATH',tmp/'caja.json'),patch.object(sam_service,'CONFIG_PATH',cfg):
                engine=Engine(Vision(),Source(),publish=True)
                self.assertFalse(engine.snapshot()['stale']);self.assertIsNone(engine.snapshot()['people_in_store'])


if __name__=='__main__':unittest.main()
