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

def pick_video():
    """Deterministic fixture selection; never depend on arbitrary glob order."""
    override=os.getenv('MOSCEYE_VIDEO')
    if override:
        path=Path(override).expanduser()
        return path if path.exists() else None
    folder=HERE.parent/'camara footage para test'
    preferred=folder/'principal.mp4'
    if preferred.exists():return preferred
    videos=sorted(folder.glob('*.mp4'))
    return videos[0] if videos else None

VIDEO=pick_video()
RUNTIME=Path(os.getenv('MOSCEYE_RUNTIME_DIR','/tmp'))
RUNTIME.mkdir(parents=True,exist_ok=True)
CAJA_PATH=RUNTIME/'caja_status.json'
STATE_PATH=RUNTIME/'mosceye_status.json'
TRIGGER_PATH=RUNTIME/'mosceye_trigger.json'
ACK_PATH=RUNTIME/'mosceye_trigger_ack.json'
LOG_PATH=RUNTIME/'mosceye_watch.log'
CONFIG_PATH=HERE/'camera_config.json'
INFERENCE_TIMEOUT=float(os.getenv('MOSCEYE_INFERENCE_TIMEOUT','30'))


def log_runtime(message):
    try:
        with open(LOG_PATH,'a',encoding='utf-8') as f:
            f.write(f'{timestamp()} {message}\n')
    except OSError:
        pass


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
        self.watchdog=None;self.request_started=0.;self.timed_out_request=None
        self.inference_timeout=INFERENCE_TIMEOUT;self.empty_minutes=None;self._last_nonempty=None
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
            total_ms=None,people=None,empty_minutes=None,stale=False,store_total_available=False,
            source=self.config['source'],config_version=self.config['version'],
            detector='fasterrcnn-resnet50-fpn-v2',model='sam1-vit_b-box-prompts',status='sin_datos')
        if publish:self._restore_last()

    def _restore_last(self):
        """Keep the last good result across restarts, explicitly marked stale."""
        try:
            if not STATE_PATH.exists() or time.time()-STATE_PATH.stat().st_mtime>86400:return
            last=json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except (OSError,ValueError):return
        if not isinstance(last,dict) or last.get('schema_version')!=2 or not last.get('counts_ready'):return
        fields=('counts_ready','people_in_queue','people_in_store','cashier_present','cashier_count',
                'zones_calibrated','captured_at','captured_epoch','timestamp','frame_id',
                'detections','masks','masks_total','inference_ms','detector_ms','sam_ms',
                'frame_w','frame_h','detector','model','total_ms','people','frame_time_sec',
                'source','config_version','empty_minutes','store_total_available')
        for key in fields:
            if key in last:self.state[key]=last[key]
        self.state.update(phase='idle',ready=False,checking=False,busy=False,error=None,warning=None,
                          masks_pending=False,store_calibrated=bool(last.get('store_calibrated')),
                          store_total_available=bool(last.get('people_in_store') is not None),
                          stale=True,status='dato_anterior')

    def start(self):
        self._ensure_watchdog()
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

    def _reset_result_state(self,**overrides):
        """Clear every field derived from a previous request, not just the obvious ones."""
        defaults=dict(phase='idle',request_id=None,client_request_id=None,checking=False,busy=False,
            error=None,warning=None,counts_ready=False,people_in_queue=None,people_in_store=None,
            cashier_present=None,cashier_count=None,store_calibrated=False,zones_calibrated=False,
            frame_id=None,captured_at=None,captured_epoch=0,timestamp=None,completed_at=None,
            frame_time_sec=None,inference_ms=None,detector_ms=None,sam_ms=None,frame_w=None,
            frame_h=None,detections=[],masks=[],masks_total=0,masks_pending=False,total_ms=None,
            people=None,empty_minutes=None,stale=False,store_total_available=False,status='sin_datos')
        defaults.update(overrides)
        self.state.update(defaults)
        self.timed_out_request=None;self.empty_minutes=None

    def _ensure_watchdog(self):
        if self.watchdog and self.watchdog.is_alive():return
        self.watchdog=threading.Thread(target=self._watchdog,daemon=True,name='inference-watchdog')
        self.watchdog.start()

    def _watchdog(self):
        """Release a stuck request even if a native inference call never returns."""
        while not self.shutdown.wait(.25):
            with self.lock:
                if not self.state['busy'] or not self.request_started:continue
                elapsed=time.monotonic()-self.request_started
                if elapsed<=self.inference_timeout:continue
                self.timed_out_request=self.state['request_id']
                self.state.update(phase='error',checking=False,busy=False,counts_ready=False,
                    masks_pending=False,error=f'Tiempo de inferencia agotado ({elapsed:.0f} s). Reintenta.',
                    status='error',completed_at=timestamp(),total_ms=round(elapsed*1000))
                log_runtime(f'watchdog: request {self.timed_out_request} timed out after {elapsed:.1f}s')
                self._publish()

    def _publish(self):
        # Called with engine lock held. Immutable snapshots + unique temp files.
        if not self.publish_files:return
        atomic_json(STATE_PATH,self.state)
        payload={k:self.state[k] for k in ['schema_version','request_id','client_request_id','phase',
            'counts_ready','checking','busy','masks_pending','error','people_in_queue','people_in_store','cashier_present',
            'store_calibrated','zones_calibrated','captured_at','timestamp','frame_id','stale','empty_minutes']}
        payload.update(captured_epoch=self.state.get('captured_epoch',0),published_epoch=time.time())
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
            self._reset_result_state(phase='detecting',request_id=request_id,client_request_id=client_request_id,
                checking=True,busy=True,zones_calibrated=cfg['zones_calibrated'],
                captured_epoch=datetime.fromisoformat(frame.captured_at).timestamp(),source=frame.source,
                config_version=cfg['version'],
                **{k:v for k,v in frame.metadata().items() if k not in ('url','source','source_version')})
            self.request_started=time.monotonic();self._ensure_watchdog()
            self._publish()
            self.worker=threading.Thread(target=self._run,args=(frame,cfg,request_id),daemon=True,name='inference')
            try:self.worker.start()
            except Exception:
                self.state.update(checking=False,busy=False,phase='error',error='No se pudo iniciar el chequeo.')
                self._publish();raise
            return self.snapshot()

    def _run(self,frame,cfg,request_id):
        start=time.perf_counter()
        def still_current():
            return request_id==self.state['request_id'] and request_id!=self.timed_out_request
        try:
            result=self.vision.detect(frame.image,cfg)
            if request_id==self.timed_out_request:return
            queue=result['people_in_queue']
            now=time.monotonic()
            if queue is None or queue>0 or result.get('cashier_present') is False:
                if queue is None:empty=None
                else:
                    self._last_nonempty=now;empty=0
            else:
                # First observation of an empty lane: unknown, not a fabricated zero.
                empty=None if self._last_nonempty is None else max(0,int((now-self._last_nonempty)//60))
            self.empty_minutes=empty
            with self.lock:
                if not still_current():return
                self.state.update(**result,phase='result',checking=False,counts_ready=True,
                    timestamp=timestamp(),inference_ms=round((time.perf_counter()-start)*1000),
                    status='sin_calibrar' if queue is None else ('vacia' if queue==0 else ('cola' if queue>=5 else 'ok')),
                    empty_minutes=empty,stale=False,
                    masks_pending=bool(cfg['sam_enabled'] and self.vision.sam and result['detections']))
                self._publish()
            if cfg['sam_enabled'] and self.vision.sam and result['detections']:
                try:
                    masks,ms=self.vision.segment(frame.image,result['detections'])
                    with self.lock:
                        if still_current():self.state.update(masks=masks,masks_total=len(masks),sam_ms=ms)
                except Exception as e:
                    with self.lock:
                        if still_current():self.state['warning']='El conteo está listo; SAM no pudo completar los contornos: '+str(e)
            elif cfg['sam_enabled'] and self.vision.sam_error:
                with self.lock:
                    if still_current():self.state['warning']=self.vision.sam_error
        except Exception as e:
            with self.lock:
                if still_current():
                    self.state.update(phase='error',error=str(e),counts_ready=False,status='error')
        finally:
            with self.lock:
                if still_current():
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
            self._last_nonempty=None
            self._reset_result_state(phase='idle',config_version=new['version'],source=new['source'],
                zones_calibrated=new['zones_calibrated'])
            self.frame=None;self._publish()
            return deepcopy(new)

    def begin_demo(self):
        """EMPEZAR on Charm: restart the footage and drop the previous analysis.

        The demo always starts from a clean slate instead of leaving the last
        SAM result on screen. A check already in flight is never interrupted.
        """
        with self.lock:
            if self.state['busy']:
                raise BusyError('Hay un chequeo en curso. Espera a que termine.')
            self.source.play(True,0.)
            if not self.state['ready']:return
            self._last_nonempty=None
            self._reset_result_state(zones_calibrated=self.config['zones_calibrated'],
                source=self.config['source'],config_version=self.config['version'])
            self.frame=None
            self._publish()

    def _handle_signal(self,msg):
        if not isinstance(msg,dict):
            log_runtime(f'trigger ignored, expected an object: {msg!r}')
            return
        action=msg.get('action');client_id=msg.get('request_id')
        if action=='start':
            try:self.begin_demo()
            except Exception as e:log_runtime(f'start signal ignored: {e}')
            return
        if action=='stop':
            # Leaving the demo does not stop the camera or the service.
            return
        if action=='check':
            try:
                reply=self.submit(client_request_id=client_id)
                atomic_json(ACK_PATH,dict(client_request_id=client_id,request_id=reply['request_id'],error=None))
            except Exception as e:
                atomic_json(ACK_PATH,dict(client_request_id=client_id,request_id=None,error=str(e)))

    def _watch_signals(self):
        last=TRIGGER_PATH.stat().st_mtime_ns if TRIGGER_PATH.exists() else 0
        heartbeat=0.;last_log=0.
        while not self.shutdown.wait(.08):
            try:
                sig=TRIGGER_PATH.stat().st_mtime_ns
                if sig==last:continue
                msg=json.loads(TRIGGER_PATH.read_text());last=sig
                self._handle_signal(msg)
            except (FileNotFoundError,json.JSONDecodeError,OSError) as e:
                if time.monotonic()-last_log>5:
                    log_runtime(f'trigger unreadable: {e}');last_log=time.monotonic()
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
    token=os.getenv('MOSCEYE_TOKEN')
    if token:
        @app.middleware('http')
        async def require_token(request,call_next):
            if request.url.path in ('/health','/assets/emblema-mosceye.png','/assets/app-icon.png','/assets/Montserrat.ttf'):
                return await call_next(request)
            if request.client and request.client.host in ('127.0.0.1','::1'):
                return await call_next(request)
            if request.headers.get('authorization')!=f'Bearer {token}':
                return JSONResponse(dict(detail='No autorizado. Envía Authorization: Bearer <MOSCEYE_TOKEN>.'),status_code=401)
            return await call_next(request)
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
        # Snapshot under the lock; annotate and encode outside it so the engine stays free.
        with engine.lock:
            if not engine.frame:raise HTTPException(404,'Aún no hay resultado.')
            frame=engine.frame;detections=engine.state['detections'];masks=engine.state['masks']
        image=annotate(frame.image,detections,masks)
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
    host=os.getenv('MOSCEYE_HOST','127.0.0.1')
    if host not in ('127.0.0.1','localhost','::1') and not os.getenv('MOSCEYE_TOKEN'):
        raise SystemExit('MOSCEYE_HOST no es local. Define MOSCEYE_TOKEN o usa 127.0.0.1.')
    engine=Engine()
    uvicorn.run(create_app(engine),host=host,port=int(os.getenv('MOSCEYE_PORT','8000')),log_level='warning')

if __name__=='__main__':main()
