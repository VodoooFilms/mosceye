"""Read-only inference benchmark on the same fixed frame. Run from any cwd."""
import sys, time, json
from pathlib import Path
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from legacy_service import service as s
out = Path(__file__).resolve().parent / 'evidence'
s.load_sam()
gen=s._predictor['gen']
cap=cv2.VideoCapture(str(s.ROOT/'camara footage para test/HD CCTV Camera video 3MP 4MP iProx CCTV HDCCTVCameras.net retail store.mp4'))
cap.set(cv2.CAP_PROP_POS_MSEC,8000); ok,frame=cap.read();cap.release()
assert ok
from segment_anything.utils.amg import build_all_layer_point_grids
rows=[]
for pps,progressive in [(32,False),(32,True),(20,False),(16,False)]:
 gen.point_grids=build_all_layer_point_grids(pps,0,1)
 start=time.perf_counter()
 r=s.analyze_frame(frame,gen=gen,on_progress=(lambda *args: None) if progressive else None)
 elapsed=time.perf_counter()-start
 row=dict(pps=pps,progressive=progressive,seconds=round(elapsed,3),masks=len(r['masks']),queue=r['people_in_queue'],store=r['people_in_store'],boxes=[m['bbox'] for m in r['people_masks']])
 rows.append(row);print(json.dumps(row),flush=True)
 cv2.imwrite(str(out/f'pps-{pps}-{progressive}.jpg'),s.annotate(frame,r))
 (out/'benchmark.json').write_text(json.dumps(rows,indent=2))
