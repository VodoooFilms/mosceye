import os
os.environ['PYTORCH_ENABLE_MPS_FALLBACK']='1'
import cv2,torch,torchvision,time,json,pathlib
from torchvision.models import detection as d
torch.set_num_threads(4)
p=pathlib.Path(__file__).resolve().parent
f=cv2.imread(str(p/'evidence/video-0-8s.jpg'))
x=torch.from_numpy(cv2.cvtColor(f,cv2.COLOR_BGR2RGB)).permute(2,0,1).float()/255
rows=[]
for name,make,weights in [('ssdlite',d.ssdlite320_mobilenet_v3_large,d.SSDLite320_MobileNet_V3_Large_Weights.DEFAULT),('faster320',d.fasterrcnn_mobilenet_v3_large_320_fpn,d.FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT)]:
 model=make(weights=weights).eval()
 for device in ['cpu','mps']:
  try:
   model.to(device); inp=x.to(device); elapsed=[]
   for i in range(3):
    t=time.perf_counter()
    with torch.inference_mode(): r=model([inp])[0]
    r={k:v.cpu() for k,v in r.items()}
    elapsed.append(round(time.perf_counter()-t,3))
   keep=(r['labels']==1)&(r['scores']>=.5)
   boxes=r['boxes'][keep].tolist();scores=r['scores'][keep].tolist()
   row=dict(model=name,device=device,seconds=elapsed,boxes=boxes,scores=scores); rows.append(row); print(json.dumps(row),flush=True)
   out=f.copy()
   for i,(box,score) in enumerate(zip(boxes,scores)):
    a,b,c,e=map(int,box);cv2.rectangle(out,(a,b),(c,e),(0,140,255),2);cv2.putText(out,f'{i+1} {score:.2f}',(a,max(b,20)),0,.65,(0,140,255),2)
   cv2.imwrite(str(p/f'evidence/detector-{name}-{device}.jpg'),out)
  except Exception as ex: print(name,device,str(ex),flush=True)
 (p/'evidence/detector-benchmark.json').write_text(json.dumps(rows,indent=2))
