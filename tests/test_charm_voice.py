"""Render, microphone lifecycle and draft validation with SDL's dummy audio driver.

No microphone, clipboard, browser or WhatsApp send is used by these tests.
"""
import os
import subprocess
import tempfile
import time
import unittest
import wave
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / 'muse-gadget-sdk/esp32/simulator/build/muse_simulator'


@unittest.skipUnless(BINARY.exists(), 'Build Charm first.')
class CharmVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.env = {**os.environ, 'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy',
                    'TMPDIR': str(self.folder), 'MOSCEYE_STATUS_PATH': str(self.folder / 'missing.json')}

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self, name, actions, headless=False):
        scenario = self.folder / (name + '.txt')
        scenario.write_text('retail=true\nstart=true\nadvance=100\n' + actions + '\nadvance=100\n')
        output = self.folder / (name + '.ppm')
        args = [str(BINARY), '--scenario', str(scenario), '--run-ms', '0', '--screenshot', str(output)]
        if headless:
            args.append('--headless')
        proc = subprocess.Popen(args, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return proc, output

    def render(self, name, actions):
        proc, output = self.launch(name, actions, headless=True)
        _, errors = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, errors.decode())
        return np.array(Image.open(output))

    def test_cashier_touch_opens_voice_from_both_pages(self):
        expected = self.render('expected', 'voice=open')
        for name, prefix in [('queue', ''), ('store', 'store=true\n')]:
            actual = self.render(name, prefix + 'tap=353,286')
            self.assertTrue(np.array_equal(expected, actual), name)

    def test_audio_is_real_pcm_wav_and_cancel_removes_draft(self):
        proc, _ = self.launch('record', 'voice=open\nvoice=record\nadvance=900\nvoice=stop\nadvance=1500\nvoice=close')
        try:
            deadline = time.monotonic() + 4
            paths = []
            while time.monotonic() < deadline and proc.poll() is None:
                paths = list(self.folder.glob('mosceye-voice-*/draft.wav'))
                if paths and paths[0].stat().st_size > 44:
                    break
                time.sleep(.04)
            self.assertTrue(paths, 'No review draft was created')
            with wave.open(str(paths[0])) as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
                self.assertGreater(wav.getnframes(), 8000)
                self.assertLessEqual(wav.getnframes(), 30 * 16000)
            _, errors = proc.communicate(timeout=8)
            self.assertEqual(proc.returncode, 0, errors.decode())
            self.assertFalse(list(self.folder.glob('mosceye-voice-*')))
        finally:
            if proc.poll() is None:
                proc.kill(); proc.communicate()

    def test_short_recording_cannot_be_shared(self):
        proc, _ = self.launch('short', 'voice=open\nvoice=record\nadvance=100\nvoice=stop\nvoice=share\nadvance=300')
        _, errors = proc.communicate(timeout=6)
        self.assertEqual(proc.returncode, 0, errors.decode())
        self.assertFalse(list(self.folder.glob('mosceye-voice-*')))

    def test_listen_then_repeat_clears_audio_and_restores_record_control(self):
        expected = self.render('idle', 'voice=open')
        proc, output = self.launch('repeat', 'voice=open\nvoice=record\nadvance=800\nvoice=stop\n'
                                  'voice=listen\nadvance=150\nvoice=repeat\nadvance=200')
        _, errors = proc.communicate(timeout=8)
        self.assertEqual(proc.returncode, 0, errors.decode())
        actual = np.array(Image.open(output))
        self.assertTrue(np.array_equal(expected[:350], actual[:350]))
        self.assertFalse(list(self.folder.glob('mosceye-voice-*')))

    def test_close_returns_to_same_metric_page(self):
        for page in ['store=false', 'store=true']:
            expected = self.render('before', page)
            actual = self.render('after', page + '\nvoice=open\nvoice=close')
            self.assertTrue(np.array_equal(expected, actual))


if __name__ == '__main__':
    unittest.main()
