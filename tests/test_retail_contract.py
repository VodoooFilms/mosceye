"""The mock retail writer must satisfy the same v2 contract as the real server."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MOCK=ROOT/'muse-gadget-sdk'/'skills'/'retail-tracker'/'mock_retail_data.py'
REQUIRED={'schema_version','request_id','client_request_id','phase','counts_ready','checking',
          'busy','masks_pending','error','people_in_queue','people_in_store','cashier_present',
          'store_calibrated','zones_calibrated','captured_at','timestamp','frame_id','stale',
          'empty_minutes','captured_epoch','published_epoch'}


class RetailContractTests(unittest.TestCase):
    def test_mock_emits_v2_contract(self):
        if not MOCK.exists():self.skipTest('retail-tracker skill not present')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'caja_status.json'
            subprocess.run([sys.executable,str(MOCK),'--once','--path',str(out)],
                           check=True,capture_output=True,text=True)
            data=json.loads(out.read_text(encoding='utf-8'))
        self.assertTrue(REQUIRED.issubset(data),sorted(REQUIRED-set(data)))
        self.assertEqual(data['schema_version'],2)
        self.assertTrue(data['counts_ready']);self.assertFalse(data['stale'])
        self.assertGreater(data['published_epoch'],0)
        self.assertGreaterEqual(data['people_in_store'],data['people_in_queue'])


if __name__=='__main__':unittest.main()
