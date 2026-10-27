"""Core regressions: concurrency, provenance, error recovery and coherent counts."""
import sys,time,threading,unittest
from pathlib import Path
from copy import deepcopy
import cv2,numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera import Frame,timestamp
from sam_service import Engine,BusyError,validate_config
from vision import classify_people,DEFAULT_ZONES

class Source:
    def __init__(self):
        image=np.zeros((720,1270,3),np.uint8)
        self.frame=Frame('frame-1',image,b'jpg',timestamp(),'footage',1,8.)
    def latest(self,frame_id=None):
        if frame_id and frame_id!=self.frame.id:raise ValueError('expired')
        return self.frame
    def status(self):return dict(source_version=1,playing=True)

class Vision:
    sam=None;sam_error=None;device='cpu'
    def __init__(self):self.entered=threading.Event();self.release=threading.Event();self.fail=False;self.seen=[]
    def detect(self,image,config):
        self.seen.append(deepcopy(config));self.entered.set();self.release.wait(2)
        if self.fail:raise RuntimeError('camera/detection failure')
        return {**classify_people([[250,50,320,280],[10,100,110,400]],[.9,.8],image.shape,config['zones'],config['zones_calibrated']), 'detector_ms':1}

def engine():
    v=Vision();e=Engine(v,Source(),publish=False);e.state['ready']=True
    return e,v

def finish(e,v):
    v.release.set();e.worker.join(3)
    assert not e.worker.is_alive()

class CoreTests(unittest.TestCase):
    def test_twenty_concurrent_requests_admit_one(self):
        e,v=engine();accepted=[];rejected=[]
        def call():
            try:accepted.append(e.submit())
            except BusyError:rejected.append(True)
        threads=[threading.Thread(target=call) for _ in range(20)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(accepted),1);self.assertEqual(len(rejected),19)
        finish(e,v);self.assertFalse(e.snapshot()['busy']);self.assertTrue(e.snapshot()['counts_ready'])

    def test_failure_releases_and_next_request_succeeds(self):
        e,v=engine();v.fail=True;e.submit();finish(e,v)
        self.assertEqual(e.snapshot()['phase'],'error');self.assertFalse(e.snapshot()['busy'])
        v.fail=False;e.submit();finish(e,v);self.assertTrue(e.snapshot()['counts_ready'])

    def test_snapshot_not_mutated_by_new_frame(self):
        e,v=engine();r=e.submit('frame-1');old=e.frame
        e.source.frame=Frame('frame-2',old.image,b'new',timestamp(),'footage',1,9.)
        finish(e,v);self.assertEqual(e.snapshot()['frame_id'],'frame-1');self.assertIs(e.frame,old)
        self.assertEqual(e.snapshot()['request_id'],r['request_id'])

    def test_expired_frame_is_rejected_without_reservation(self):
        e,v=engine()
        with self.assertRaises(ValueError):e.submit('old')
        self.assertFalse(e.snapshot()['busy']);self.assertIsNone(e.worker)

    def test_config_is_locked_while_running(self):
        e,v=engine();e.submit()
        with self.assertRaises(BusyError):e.configure({'confidence':.8})
        finish(e,v);self.assertEqual(v.seen[0]['confidence'],.65)

    def test_queue_and_staff_are_disjoint_subsets_of_visible(self):
        result=classify_people([[250,50,320,280],[10,100,110,400],[800,200,900,600]], [.9]*3,(720,1270,3),DEFAULT_ZONES)
        self.assertEqual(result['people_in_store'],3);self.assertEqual(result['people_in_queue'],1)
        self.assertEqual(result['cashier_count'],1)
        self.assertLessEqual(result['people_in_queue']+result['cashier_count'],result['people_in_store'])

    def test_overlap_does_not_merge_distinct_people(self):
        r=classify_people([[220,30,280,280],[240,50,300,290]],[.9,.8],(720,1270,3),DEFAULT_ZONES)
        self.assertEqual(r['people_in_store'],2);self.assertEqual(r['people_in_queue'],2)

    def test_zones_are_resolution_independent(self):
        a=classify_people([[250,50,320,280]],[.9],(720,1270,3),DEFAULT_ZONES)
        b=classify_people([[1000,200,1280,1120]],[.9],(2880,5080,3),DEFAULT_ZONES)
        self.assertEqual(a['people_in_queue'],b['people_in_queue'])

    def test_uncalibrated_queue_is_unknown_not_zero(self):
        r=classify_people([[250,50,320,280]],[.9],(720,1270,3),DEFAULT_ZONES,False)
        self.assertIsNone(r['people_in_queue']);self.assertIsNone(r['cashier_present']);self.assertEqual(r['people_in_store'],1)
        self.assertFalse(r['store_calibrated']);self.assertTrue(r['store_total_available'])

    def test_source_change_invalidates_zone_calibration(self):
        e,v=engine();cfg=validate_config({'source':'camera'},e.config)
        self.assertFalse(cfg['zones_calibrated'])

    def test_invalid_configuration_rejected(self):
        e,v=engine()
        for changes in [{'source':'other'},{'confidence':float('nan')},{'camera_index':True},{'zones':{'queue':[]}}, {'sam_enabled':'yes'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_config(changes,e.config)

    def test_reconfigure_clears_result_provenance(self):
        e,v=engine();e.submit();finish(e,v)
        self.assertTrue(e.snapshot()['captured_at'])
        e.configure({'confidence':.7})
        for field in ['request_id','frame_id','captured_at','timestamp','inference_ms']:
            self.assertIsNone(e.snapshot()[field])
        self.assertFalse(e.snapshot()['counts_ready'])

    def test_reconfigure_clears_every_derived_field(self):
        e,v=engine();e.submit();finish(e,v)
        e.state.update(warning='stale',masks_pending=True,total_ms=99,people=7,frame_w=42,frame_h=24)
        e.configure({'confidence':.7})
        s=e.snapshot()
        for field in ['warning','total_ms','people','frame_w','frame_h','empty_minutes','completed_at']:
            self.assertIsNone(s[field],field)
        self.assertFalse(s['masks_pending']);self.assertEqual(s['detections'],[]);self.assertEqual(s['masks'],[])

    def test_uncalibrated_result_does_not_invent_empty_minutes(self):
        e,v=engine();e.configure({'zones_calibrated':False});e.submit();finish(e,v)
        s=e.snapshot()
        self.assertTrue(s['counts_ready']);self.assertIsNone(s['people_in_queue']);self.assertIsNone(s['empty_minutes'])

    def test_watchdog_releases_a_stuck_request(self):
        e,v=engine();e.inference_timeout=.15;e.submit()
        deadline=time.monotonic()+2
        while time.monotonic()<deadline and e.snapshot()['busy']:time.sleep(.02)
        s=e.snapshot()
        self.assertFalse(s['busy']);self.assertEqual(s['phase'],'error');self.assertIn('agotado',s['error'])
        v.release.set();e.worker.join(3)
        self.assertFalse(e.snapshot()['counts_ready']);self.assertFalse(e.snapshot()['busy'])

    def test_sam_failure_preserves_count(self):
        e,v=engine();v.sam=True
        def broken(*args):raise RuntimeError('mask failure')
        v.segment=broken;e.submit();finish(e,v);r=e.snapshot()
        self.assertTrue(r['counts_ready']);self.assertIsNone(r['error']);self.assertIn('mask failure',r['warning']);self.assertFalse(r['busy'])

if __name__=='__main__':unittest.main()
