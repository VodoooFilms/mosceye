"""Native-render regressions for fast drag sequences between input polling ticks."""
import json,os,subprocess,tempfile,time,unittest
from pathlib import Path
from PIL import Image
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
BINARY=ROOT/'muse-gadget-sdk/esp32/simulator/build/muse_simulator'

@unittest.skipUnless(BINARY.exists(),'Build the Charm simulator first.')
class CharmNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        fixture=dict(people_in_queue=4,people_in_store=12,cashier_present=True,zones_calibrated=True,
                     counts_ready=True,busy=False,checking=False,error=None,phase='result',
                     request_id='fixture',client_request_id=None,captured_epoch=time.time()-15,published_epoch=time.time())
        path=self.folder/'status.json';path.write_text(json.dumps(fixture))
        self.env={**os.environ,'MOSCEYE_STATUS_PATH':str(path)}
    def tearDown(self):self.tmp.cleanup()
    def render(self,name,actions):
        scenario=self.folder/f'{name}.txt';scenario.write_text('retail=true\nstart=true\nadvance=100\n'+actions+'\nadvance=600\n')
        output=self.folder/f'{name}.ppm'
        subprocess.run([str(BINARY),'--headless','--scenario',str(scenario),'--run-ms','100','--screenshot',str(output)],env=self.env,check=True,stdout=subprocess.DEVNULL,timeout=10)
        return np.array(Image.open(output))[78:376]
    def test_fast_left_swipe_selects_store_page(self):
        expected=self.render('expected','store=true')
        actual=self.render('drag','swipe=left')
        self.assertTrue(np.array_equal(actual,expected))
    def test_right_swipe_returns_to_queue(self):
        expected=self.render('expected','store=false')
        actual=self.render('drag','store=true\nswipe=right')
        self.assertTrue(np.array_equal(actual,expected))
    def test_swipe_beyond_last_page_stays_in_bounds(self):
        expected=self.render('expected','store=true')
        actual=self.render('drag','store=true\nswipe=left')
        self.assertTrue(np.array_equal(actual,expected))

    def test_drag_out_of_window_settles_on_store_page(self):
        # Regression: a real drag left the window (negative X in the LVGL log)
        # and the simulator segfaulted. Releasing outside must settle cleanly.
        expected=self.render('expected','store=true')
        actual=self.render('dragout','drag=300,180,-250,180,14')
        self.assertTrue(np.array_equal(actual,expected))

    def test_drag_out_right_returns_to_queue_page(self):
        expected=self.render('expected','store=false')
        actual=self.render('dragoutr','store=true\ndrag=100,180,700,180,14')
        self.assertTrue(np.array_equal(actual,expected))

    def test_previous_result_dims_until_new_request_arrives(self):
        previous=self.render('previous','')
        scenario=self.folder/'fresh.txt'
        scenario.write_text('retail=true\nstart=true\nadvance=900\n')
        output=self.folder/'fresh.ppm'
        proc=subprocess.Popen([str(BINARY),'--scenario',str(scenario),'--run-ms','0','--screenshot',str(output)],
                              env={**self.env,'SDL_VIDEODRIVER':'dummy'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            time.sleep(.4)
            path=Path(self.env['MOSCEYE_STATUS_PATH'])
            fixture=json.loads(path.read_text())
            fixture.update(request_id='new-check',published_epoch=time.time())
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(fixture));temp.replace(path)
            self.assertEqual(proc.wait(timeout=5),0)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
        fresh=np.array(Image.open(output))[78:376]
        # A new result must restore full brightness; previous data stays dim.
        previous_white=np.all(previous[:146]>230,axis=2).sum()
        fresh_white=np.all(fresh[:146]>230,axis=2).sum()
        self.assertLess(previous_white,20)
        self.assertGreater(fresh_white,1000)

if __name__=='__main__':unittest.main()
