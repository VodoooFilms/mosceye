"""Deterministic audit reproductions; no camera, model or running-server mutations."""
import ast, sys, json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from legacy_service import service as s
results={}
# Execute the actual HTTP handler with a valid schedule: worker starts AFTER handler returns.
tree=ast.parse(Path(s.__file__).read_text())
main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
handler=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='check')
handler.decorator_list=[]
pending=[]
class DeferredThread:
 def __init__(self,target,**kwargs): self.target=target
 def start(self): pending.append(self.target)
ns={'state':s.state,'threading':SimpleNamespace(Thread=DeferredThread),'run_check':s.run_check}
exec(compile(ast.fix_missing_locations(ast.Module(body=[handler],type_ignores=[])),'actual_check_handler','exec'),ns)
s.state['checking']=False
ns['check'](); pending.pop()()
assert s.state['checking'] and s.state['timestamp'] is None
results['http_worker_skipped_and_checking_stuck']=True
s.state['checking']=False
# Geometry, not semantics: the exact same shape passes regardless of content or frame scale.
m={'bbox':[70,50,60,120],'area':6000,'predicted_iou':.95,'segmentation':np.zeros((720,1270),bool)}
assert s.person_like(m,1270,720) and s.person_like(m,2540,1440)
scaled={**m,'bbox':[140,100,120,240],'area':24000}
assert s.person_like(scaled,2540,1440)
scaled4={**m,'bbox':[280,200,240,480],'area':96000}
assert not s.person_like(scaled4,5080,2880)
results['pixel_thresholds_reject_same_person_at_4x_resolution']=True
# Two disjoint object masks with overlapping bounding boxes: queue keeps both, store merges them.
a=np.zeros((720,1270),bool);b=a.copy()
a[50:170,200:240]=True;b[50:170,240:280]=True
m1={'bbox':[200,50,60,120],'area':4800,'predicted_iou':.95,'segmentation':a}
m2={'bbox':[220,50,60,120],'area':4800,'predicted_iou':.95,'segmentation':b}
r=s._result_from_masks(np.zeros((720,1270,3),np.uint8),[m1,m2])
assert r['people_in_queue']==2 and r['people_in_store']==1
results['queue_exceeds_store_for_overlapping_boxes']={'queue':r['people_in_queue'],'store':r['people_in_store']}
print(json.dumps(results,indent=2))
(Path(__file__).resolve().parent/'evidence/reproductions.json').write_text(json.dumps(results,indent=2))
