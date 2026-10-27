"""Semantic person detection; SAM refines only those boxes and never changes counts."""
from pathlib import Path
import time
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_ZONES = {
    'queue': [[.16,.04],[.32,.04],[.32,.70],[.16,.70]],
    'cashier': [[0,.12],[.155,.12],[.155,.72],[0,.72]],
}

def inside(point, polygon):
    return cv2.pointPolygonTest(np.asarray(polygon, dtype=np.float32), tuple(point), False) >= 0


def classify_people(boxes, scores, shape, zones, calibrated=True):
    """One detection list, disjoint roles. Counts always share the same universe."""
    h,w = shape[:2]
    people=[]
    for i,(box,score) in enumerate(zip(boxes,scores)):
        x0,y0,x1,y1 = map(float,box)
        # Bottom center approximates floor position; calibration remains scene-specific.
        anchor=[(x0+x1)/(2*w), y1/h]
        role='visible'
        if calibrated:
            if inside(anchor,zones['cashier']): role='cashier'
            elif inside(anchor,zones['queue']): role='queue'
        people.append(dict(id=f'P{i+1}',bbox=[x0,y0,x1-x0,y1-y0],score=float(score),
                           anchor=anchor,role=role))
    queue=sum(p['role']=='queue' for p in people) if calibrated else None
    cashier=sum(p['role']=='cashier' for p in people) if calibrated else None
    return dict(detections=people,people_in_store=len(people),people_in_queue=queue,
                cashier_count=cashier,cashier_present=(cashier>0) if calibrated else None,
                zones_calibrated=calibrated,store_calibrated=True,
                people=len(people),frame_w=w,frame_h=h)


class Vision:
    def __init__(self):
        self.detector=None
        self.sam=None
        self.sam_error=None

    def load(self):
        import torch
        from torchvision.models.detection import (fasterrcnn_resnet50_fpn_v2,
                                                    FasterRCNN_ResNet50_FPN_V2_Weights)
        torch.set_num_threads(4)
        self.device='mps' if torch.backends.mps.is_available() else 'cpu'
        self.detector=fasterrcnn_resnet50_fpn_v2(
            weights=FasterRCNN_ResNet50_FPN_V2_Weights.DEFAULT,progress=False,
            min_size=960,max_size=1700).eval().to(self.device)
        # Warm-up once; startup latency must not land on the first customer request.
        with torch.inference_mode():
            self.detector([torch.zeros((3,640,960),device=self.device)])
        checkpoint=HERE/'checkpoints/sam_vit_b_01ec64.pth'
        if checkpoint.exists():
            try:
                from segment_anything import sam_model_registry,SamPredictor
                model=sam_model_registry['vit_b'](checkpoint=str(checkpoint)).eval().to(self.device)
                self.sam=SamPredictor(model)
            except Exception as e:
                self.sam_error=str(e)
        else:
            self.sam_error='Checkpoint SAM no instalado; las cajas y el conteo siguen disponibles.'

    def detect(self, frame, config):
        import torch
        from torchvision.ops import nms
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        image=torch.from_numpy(rgb).permute(2,0,1).to(self.device).float()/255
        t=time.perf_counter()
        with torch.inference_mode():
            out=self.detector([image])[0]
        out={k:v.cpu() for k,v in out.items()}
        selected=(out['labels']==1)&(out['scores']>=config['confidence'])
        boxes,scores=out['boxes'][selected],out['scores'][selected]
        keep=nms(boxes,scores,.5)
        boxes,scores=boxes[keep].tolist(),scores[keep].tolist()
        # Stable numbering within this request, not identity tracking across requests.
        ordered=sorted(zip(boxes,scores),key=lambda pair:(pair[0][0],pair[0][1]))
        result=classify_people([a for a,b in ordered],[b for a,b in ordered],frame.shape,
                               config['zones'],config['zones_calibrated'])
        result['detector_ms']=round((time.perf_counter()-t)*1000)
        return result

    def segment(self, frame, detections):
        """One image embedding and batched box prompts; no automatic object grid."""
        import torch
        if not self.sam or not detections: return [],0
        start=time.perf_counter()
        h,w=frame.shape[:2]
        boxes=[]
        for p in detections:
            x,y,bw,bh=p['bbox'];boxes.append([x,y,x+bw,y+bh])
        contours=[]
        try:
            with torch.inference_mode():
                self.sam.set_image(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                prompts=self.sam.transform.apply_boxes_torch(torch.tensor(boxes,device=self.device),frame.shape[:2])
                for offset in range(0,len(prompts),8):
                    masks,qualities,_=self.sam.predict_torch(point_coords=None,point_labels=None,
                        boxes=prompts[offset:offset+8],multimask_output=False)
                    for j,mask in enumerate(masks[:,0].cpu().numpy()):
                        paths,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                        polygons=[]
                        for path in paths:
                            if cv2.contourArea(path)<80: continue
                            poly=cv2.approxPolyDP(path,2.0,True).reshape(-1,2)
                            polygons.append([[round(float(x)/w,5),round(float(y)/h,5)] for x,y in poly])
                        contours.append(dict(id=detections[offset+j]['id'],polygons=polygons,
                            mask_quality=float(qualities[j,0].item())))
        finally:
            self.sam.reset_image()
        return contours,round((time.perf_counter()-start)*1000)


def annotate(frame, detections, contours=()):
    """Export evidence only. Desktop receives a clean frame plus optional overlays."""
    out=frame.copy();h,w=frame.shape[:2]
    for m in contours:
        for poly in m['polygons']:
            pts=np.array([[x*w,y*h] for x,y in poly],np.int32)
            layer=out.copy();cv2.fillPoly(layer,[pts],(0,140,255));out=cv2.addWeighted(out,.72,layer,.28,0)
    for p in detections:
        x,y,bw,bh=map(int,p['bbox'])
        color=(0,140,255) if p['role']=='queue' else ((80,180,80) if p['role']=='cashier' else (230,210,120))
        cv2.rectangle(out,(x,y),(x+bw,y+bh),color,2)
        cv2.putText(out,f"{p['id']} {p['score']:.0%}",(x,max(18,y-6)),cv2.FONT_HERSHEY_SIMPLEX,.55,color,2)
    return out
