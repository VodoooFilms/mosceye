"""Real HTTP validation and reproducible fixed-frame latency measurements."""
import argparse,json,time,urllib.request,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import cv2,numpy as np
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8001);args=p.parse_args()
base=f'http://127.0.0.1:{args.port}/api/mosceye'
out=Path(__file__).resolve().parent/'evidence/core-v2';out.mkdir(exist_ok=True)
def api(path='',body=None):
 req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
def wait_result():
 end=time.monotonic()+30
 while time.monotonic()<end:
  s=api()
  if not s['busy']:
   assert s['phase']=='result',s
   assert s['counts_ready'] and not s['error'],s
   assert s['people_in_queue']+s['cashier_count']<=s['people_in_store'],s
   return s
  time.sleep(.04)
 raise AssertionError('request timeout')
rows=[]
for sec in [5,8,15,25,35,45,55,65,75,85,95,105]:
 api('/play',{'seek_sec':sec});api('/stop',{})
 end=time.monotonic()+3
 while True:
  frame=api('/frame')
  if abs(frame['frame_time_sec']-sec)<.3:break
  assert time.monotonic()<end;time.sleep(.04)
 # Pin the frame shown in the preview, and prove the result references it.
 accepted=api('/check',{'frame_id':frame['frame_id']})
 s=wait_result();assert s['frame_id']==frame['frame_id'] and s['request_id']==accepted['request_id']
 (out/f'{sec:03d}.json').write_text(json.dumps(s,indent=2))
 for name,path in [('raw',f'/capture.jpg?request_id={s["request_id"]}'),('boxes','/preview.jpg')]:
  (out/f'{sec:03d}-{name}.jpg').write_bytes(urllib.request.urlopen(base+path).read())
 row={k:s[k] for k in ['frame_time_sec','people_in_queue','people_in_store','cashier_count','inference_ms','sam_ms','total_ms','masks_total']};rows.append(row);print(json.dumps(row),flush=True)
# 20 consecutive real requests at one frame; SAM off to isolate request admission/detection.
original=api('/config');api('/config',{'sam_enabled':False})
sequential=[]
for _ in range(20):
 accepted=api('/check',{});s=wait_result();assert s['request_id']==accepted['request_id'];sequential.append(s['inference_ms'])
# A burst must reserve one worker, never silently stall.
def submit(_):
 try:api('/check',{});return 202
 except urllib.error.HTTPError as e:return e.code
with ThreadPoolExecutor(max_workers=8) as pool:codes=list(pool.map(submit,range(8)))
assert codes.count(202)==1 and codes.count(409)==7,codes
wait_result();api('/config',{'sam_enabled':original['sam_enabled']})
# Expired explicit frame must fail without consuming the worker slot.
try:api('/check',{'frame_id':'expired-frame'});raise AssertionError('accepted expired')
except urllib.error.HTTPError as e:assert e.code==409
assert not api()['busy']
metrics=dict(frames=rows,sequential_20_ms=sequential,concurrent_codes=codes,
             count_p50_ms=float(np.percentile([r['inference_ms'] for r in rows],50)),
             count_p95_ms=float(np.percentile([r['inference_ms'] for r in rows],95)),
             total_p50_ms=float(np.percentile([r['total_ms'] for r in rows],50)),
             total_p95_ms=float(np.percentile([r['total_ms'] for r in rows],95)))
(out/'validation.json').write_text(json.dumps(metrics,indent=2));print(json.dumps(metrics),flush=True)
# Contact sheet for manual counting review, independent from model predictions.
for style in ['raw','boxes']:
 tiles=[]
 for sec in [5,8,15,25,35,45,55,65,75,85,95,105]:
  img=cv2.imread(str(out/f'{sec:03d}-{style}.jpg'));img=cv2.resize(img,(635,360))
  tile=np.full((390,635,3),245,np.uint8);tile[30:]=img;cv2.putText(tile,f'FRAME {sec}s',(12,21),0,.6,(30,30,30),1);tiles.append(tile)
 sheet=np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,12,3)])
 cv2.imwrite(str(out/f'contact-{style}.jpg'),sheet)
