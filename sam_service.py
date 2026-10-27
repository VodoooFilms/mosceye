#!/usr/bin/env python3
"""MOSCEYE edge: one request, one frame, semantic people boxes, optional SAM masks."""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime
from copy import deepcopy
import json,os,tempfile,threading,time,uuid
from pathlib import Path
import cv2
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse,JSONResponse,Response,StreamingResponse
from pydantic import BaseModel,Field
from camera import FrameSource,timestamp
from vision import Vision,DEFAULT_ZONES,annotate

HERE=Path(__file__).resolve().parent
VIDEO=next((HERE.parent/'camara footage para test').glob('*.mp4'),None)
RUNTIME=Path(os.getenv('MOSCEYE_RUNTIME_DIR','/tmp'))
RUNTIME.mkdir(parents=True,exist_ok=True)
CAJA_PATH=RUNTIME/'caja_status.json'
STATE_PATH=RUNTIME/'mosceye_status.json'
TRIGGER_PATH=RUNTIME/'mosceye_trigger.json'
ACK_PATH=RUNTIME/'mosceye_trigger_ack.json'
CONFIG_PATH=HERE/'camera_config.json'


def atomic_json(path,payload):
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,allow_nan=False)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


class BusyError(Exception):pass

class Engine:
    def __init__(self,vision=None,source=None,publish=True):
        self.vision=vision or Vision()
        self.source=source or FrameSource(VIDEO or '')
        self.lock=threading.RLock();self.publish_files=publish
        self.shutdown=threading.Event();self.worker=None;self.frame=None
        self.config=dict(source='footage',camera_index=0,confidence=.65,sam_enabled=True,
                         zones=deepcopy(DEFAULT_ZONES),zones_calibrated=True,version=1)
        if publish and CONFIG_PATH.exists():
            try:self.config.update(validate_config(json.loads(CONFIG_PATH.read_text()),self.config))
            except (ValueError,TypeError):pass
        self.state=dict(schema_version=2,ready=False,device='loading',phase='idle',request_id=None,
            client_request_id=None,checking=False,busy=False,error=None,warning=None,
            counts_ready=False,people_in_queue=None,people_in_store=None,cashier_present=None,
            cashier_count=None,store_calibrated=False,zones_calibrated=False,
            frame_id=None,captured_at=None,timestamp=None,completed_at=None,
            frame_time_sec=None,inference_ms=None,detector_ms=None,sam_ms=None,
            frame_w=None,frame_h=None,detections=[],masks=[],masks_total=0,masks_pending=False,
            source=self.config['source'],config_version=self.config['version'],
            detector='fasterrcnn-resnet50-fpn-v2',model='sam1-vit_b-box-prompts',status='sin_datos')

    def start(self):
        self.source.configure(self.config['source'],self.config['camera_index']);self.source.start()
        try:
            self.vision.load()
            with self.lock:
                self.state.update(ready=True,device=self.vision.device,warning=self.vision.sam_error)
                self._publish()
        except Exception as e:
            with self.lock:self.state.update(error=str(e),phase='error',status='error');self._publish()
        threading.Thread(target=self._watch_signals,daemon=True,name='charm-signals').start()

    def close(self):
        self.shutdown.set()
        if self.worker:self.worker.join(timeout=20)
        self.source.close()

    def snapshot(self):
        with self.lock:
            return {**deepcopy(self.state),'config':deepcopy(self.config),**self.source.status()}

    def _publish(self):
        # Called with engine lock held. Immutable snapshots + unique temp files.
        if not self.publish_files:return
        atomic_json(STATE_PATH,self.state)
        payload={k:self.state[k] for k in ['schema_version','request_id','client_request_id','phase',
            'counts_ready','checking','busy','masks_pending','error','people_in_queue','people_in_store','cashier_present',
            'store_calibrated','zones_calibrated','captured_at','timestamp','frame_id']}
        payload.update(empty_minutes=0,captured_epoch=self.state.get('captured_epoch',0),
                       published_epoch=time.time())
        atomic_json(CAJA_PATH,payload)

    def submit(self,frame_id=None,client_request_id=None):
        with self.lock:
            if not self.state['ready']:raise RuntimeError(self.state['error'] or 'El motor está iniciando.')
            if self.state['busy']:raise BusyError('Hay un chequeo en curso. Espera a que termine.')
            request_id=uuid.uuid4().hex
            cfg=deepcopy(self.config)
            # Pin the exact buffered frame BEFORE dispatch; unknown frame is an explicit error.
            frame=self.source.latest(frame_id)
            if frame.source!=cfg['source'] or frame.source_version!=self.source.status()['source_version']:
                raise RuntimeError('La fuente está cambiando. Espera un instante y vuelve a chequear.')
            self.frame=frame
            self.state.update(phase='detecting',request_id=request_id,client_request_id=client_request_id,
                checking=True,busy=True,error=None,warning=None,counts_ready=False,
                people_in_queue=None,people_in_store=None,cashier_present=None,cashier_count=None,
                detections=[],masks=[],masks_total=0,masks_pending=False,inference_ms=None,
                detector_ms=None,sam_ms=None,completed_at=None,timestamp=None,
                captured_epoch=datetime.fromisoformat(frame.captured_at).timestamp(),source=frame.source,config_version=cfg['version'],
                **{k:v for k,v in frame.metadata().items() if k not in ('url','source','source_version')})
            self._publish()
            self.worker=threading.Thread(target=self._run,args=(frame,cfg,request_id),daemon=True,name='inference')
            try:self.worker.start()
            except Exception:
                self.state.update(checking=False,busy=False,phase='error',error='No se pudo iniciar el chequeo.')
                self._publish();raise
            return self.snapshot()

    def _run(self,frame,cfg,request_id):
        start=time.perf_counter()
        try:
            result=self.vision.detect(frame.image,cfg)
            queue=result['people_in_queue']
            with self.lock:
                self.state.update(**result,phase='result',checking=False,counts_ready=True,
                    timestamp=timestamp(),inference_ms=round((time.perf_counter()-start)*1000),
                    status='sin_calibrar' if queue is None else ('vacia' if queue==0 else ('cola' if queue>=5 else 'ok')),
                    masks_pending=bool(cfg['sam_enabled'] and self.vision.sam and result['detections']))
                self._publish()
            if cfg['sam_enabled'] and self.vision.sam and result['detections']:
                try:
                    masks,ms=self.vision.segment(frame.image,result['detections'])
                    with self.lock:self.state.update(masks=masks,masks_total=len(masks),sam_ms=ms)
                except Exception as e:
                    with self.lock:self.state['warning']='El conteo está listo; SAM no pudo completar los contornos: '+str(e)
            elif cfg['sam_enabled'] and self.vision.sam_error:
                with self.lock:self.state['warning']=self.vision.sam_error
        except Exception as e:
            with self.lock:self.state.update(phase='error',error=str(e),counts_ready=False,status='error')
        finally:
            with self.lock:
                self.state.update(checking=False,busy=False,masks_pending=False,completed_at=timestamp(),
                                  total_ms=round((time.perf_counter()-start)*1000))
                self._publish()

    def configure(self,body):
        with self.lock:
            if self.state['busy']:raise BusyError('Espera a que termine el chequeo antes de configurar.')
            new=validate_config(body,self.config)
            new['version']=self.config['version']+1
            changed=any(new[k]!=self.config[k] for k in ('source','camera_index'))
            if changed and new['source']=='camera':
                result=probe_camera(new['camera_index'])
                if not result['ok']:raise ValueError(result['error'])
            if self.publish_files:atomic_json(CONFIG_PATH,new)
            self.config=new
            if changed:self.source.configure(new['source'],new['camera_index'])
            self.state.update(phase='idle',counts_ready=False,error=None,status='sin_datos',
                request_id=None,frame_id=None,detections=[],masks=[],masks_total=0,
                people_in_queue=None,people_in_store=None,cashier_present=None,cashier_count=None,
                captured_at=None,captured_epoch=0,timestamp=None,completed_at=None,frame_time_sec=None,
                inference_ms=None,detector_ms=None,sam_ms=None,config_version=new['version'],source=new['source'])
            self.frame=None;self._publish()
            return deepcopy(new)

    def _watch_signals(self):
        last=TRIGGER_PATH.stat().st_mtime_ns if TRIGGER_PATH.exists() else 0
        heartbeat=0.
        while not self.shutdown.wait(.08):
            try:
                sig=TRIGGER_PATH.stat().st_mtime_ns
                if sig==last:continue
                msg=json.loads(TRIGGER_PATH.read_text());last=sig
                action=msg.get('action');client_id=msg.get('request_id')
                if action in ('start','stop'):
                    # Charm navigation does not control camera availability.
                    continue
                if action=='check':
                    try:
                        reply=self.submit(client_request_id=client_id)
                        atomic_json(ACK_PATH,dict(client_request_id=client_id,request_id=reply['request_id'],error=None))
                    except Exception as e:
                        atomic_json(ACK_PATH,dict(client_request_id=client_id,request_id=None,error=str(e)))
            except (FileNotFoundError,json.JSONDecodeError,OSError):pass
            finally:
                if time.monotonic()-heartbeat>=1:
                    with self.lock:self._publish()
                    heartbeat=time.monotonic()


def validate_config(body,previous):
    allowed={'source','camera_index','confidence','sam_enabled','zones','zones_calibrated','version'}
    if not isinstance(body,dict) or set(body)-allowed:raise ValueError('Configuración no reconocida.')
    cfg={**deepcopy(previous),**body}
    if cfg['source'] not in ('footage','camera'):raise ValueError('Elige video de demo o cámara.')
    if type(cfg['camera_index']) is not int or not 0<=cfg['camera_index']<=9:raise ValueError('Índice de cámara: entero de 0 a 9.')
    if type(cfg['confidence']) not in (int,float) or not .2<=cfg['confidence']<=.95:raise ValueError('Confianza entre 0.20 y 0.95.')
    if type(cfg['sam_enabled']) is not bool or type(cfg['zones_calibrated']) is not bool:raise ValueError('Opciones de calibración inválidas.')
    if not isinstance(cfg['zones'],dict) or set(cfg['zones'])!={'queue','cashier'}:raise ValueError('Define zonas de fila y personal de caja.')
    for poly in cfg['zones'].values():
        if not isinstance(poly,list) or not 3<=len(poly)<=12:raise ValueError('Cada zona necesita de 3 a 12 puntos.')
        for point in poly:
            if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not 0<=v<=1 for v in point):
                raise ValueError('Los puntos deben estar entre 0 y 1.')
        import numpy as np
        if abs(cv2.contourArea(np.asarray(poly,dtype=np.float32)))<.0001:raise ValueError('La zona no puede tener área cero.')
    if cfg['source']!=previous['source'] or cfg['camera_index']!=previous['camera_index']:
        cfg['zones_calibrated']=False
    return cfg


def probe_camera(index):
    cap=cv2.VideoCapture(index)
    try:
        if not cap.isOpened():raise RuntimeError('No se pudo abrir la cámara. Revisa conexión y permisos de macOS.')
        for _ in range(20):
            ok,frame=cap.read()
            if ok and frame.mean()>1:return dict(ok=True,width=frame.shape[1],height=frame.shape[0])
            time.sleep(.05)
        raise RuntimeError('La cámara no entregó imagen válida. Revisa permisos o la tapa.')
    except Exception as e:return dict(ok=False,error=str(e))
    finally:cap.release()


class CheckBody(BaseModel):
    frame_id:str|None=Field(default=None,max_length=80)
    client_request_id:str|None=Field(default=None,max_length=80)


def create_app(engine):
    @asynccontextmanager
    async def lifespan(app):
        threading.Thread(target=engine.start,daemon=True,name='model-startup').start()
        yield
        engine.close()
    app=FastAPI(title='MOSCEYE',lifespan=lifespan)
    @app.get('/health')
    def health():
        s=engine.snapshot()
        return dict(ok=s['ready'],ready=s['ready'],device=s['device'],error=s['error'],schema_version=2)
    @app.get('/')
    @app.get('/desktop')
    def desktop():return FileResponse(HERE/'desktop/index.html')
    @app.get('/assets/emblema-mosceye.png')
    def emblem():return FileResponse(HERE/'assets/emblema-mosceye.png')
    @app.get('/assets/app-icon.png')
    def app_icon():return FileResponse(HERE/'assets/app-icon.png',media_type='image/png')
    @app.get('/assets/Montserrat.ttf')
    def brand_font():return FileResponse(HERE/'assets/Montserrat.ttf',media_type='font/ttf')
    @app.get('/api/mosceye')
    def status():return engine.snapshot()
    @app.post('/api/mosceye/check')
    def check(body:CheckBody|None=None):
        try:return JSONResponse(engine.submit(**(body.model_dump() if body else {})),status_code=202)
        except BusyError as e:raise HTTPException(409,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
        except RuntimeError as e:raise HTTPException(503,str(e))
    @app.get('/api/mosceye/frame')
    def frame_info():
        try:return {**engine.source.latest().metadata(),**engine.source.status()}
        except RuntimeError as e:raise HTTPException(503,str(e))
    @app.get('/api/mosceye/frame.jpg')
    def frame_jpg(id:str):
        try:return Response(engine.source.latest(id).jpg,media_type='image/jpeg',headers={'Cache-Control':'no-store'})
        except ValueError as e:raise HTTPException(410,str(e))
    @app.get('/api/mosceye/capture.jpg')
    def capture(request_id:str|None=None):
        with engine.lock:
            if not engine.frame:raise HTTPException(404,'Aún no hay captura.')
            if request_id and request_id!=engine.state['request_id']:raise HTTPException(410,'Ese chequeo ya no está disponible.')
            return Response(engine.frame.jpg,media_type='image/jpeg',headers={'Cache-Control':'no-store'})
    @app.get('/api/mosceye/preview.jpg')
    def preview():
        with engine.lock:
            if not engine.frame:raise HTTPException(404,'Aún no hay resultado.')
            image=annotate(engine.frame.image,engine.state['detections'],engine.state['masks'])
        ok,jpg=cv2.imencode('.jpg',image)
        return Response(jpg.tobytes(),media_type='image/jpeg',headers={'Cache-Control':'no-store'})
    @app.get('/api/mosceye/config')
    def config():return engine.snapshot()['config']
    @app.post('/api/mosceye/config')
    def configure(body:dict):
        try:return dict(ok=True,config=engine.configure(body))
        except BusyError as e:raise HTTPException(409,str(e))
        except ValueError as e:raise HTTPException(400,str(e))
    @app.get('/api/mosceye/camera/test')
    def camera_test(index:int=0):
        if not 0<=index<=9:raise HTTPException(400,'Índice de 0 a 9.')
        with engine.lock:
            if engine.config['source']=='camera':
                try:return dict(ok=True,**engine.source.latest().metadata())
                except RuntimeError as e:return dict(ok=False,error=str(e))
        return probe_camera(index)
    @app.post('/api/mosceye/play')
    def play(body:dict|None=None):
        seek=(body or {}).get('seek_sec')
        if seek is not None and (type(seek) not in (float,int) or not 0<=seek<100000):raise HTTPException(400,'Instante inválido.')
        engine.source.play(True,seek);return engine.snapshot()
    @app.post('/api/mosceye/stop')
    def stop():engine.source.play(False);return engine.snapshot()
    @app.get('/api/mosceye/camera.mjpg')
    def stream():
        def generate():
            last=None
            while not engine.shutdown.wait(.1):
                try:
                    frame=engine.source.latest()
                    if frame.id!=last:
                        last=frame.id
                        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+frame.jpg+b'\r\n'
                except RuntimeError:continue
        return StreamingResponse(generate(),media_type='multipart/x-mixed-replace; boundary=frame')
    return app


def main():
    import uvicorn
    engine=Engine()
    uvicorn.run(create_app(engine),host=os.getenv('MOSCEYE_HOST','127.0.0.1'),port=int(os.getenv('MOSCEYE_PORT','8000')),log_level='warning')

if __name__=='__main__':main()
