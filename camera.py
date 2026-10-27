"""One frame producer shared by previews and inference; no per-client video clock."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import threading,time,uuid
import cv2


def timestamp():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')

@dataclass(frozen=True)
class Frame:
    id: str
    image: object
    jpg: bytes
    captured_at: str
    source: str
    source_version: int
    sec: float | None

    def metadata(self):
        h,w=self.image.shape[:2]
        return dict(frame_id=self.id,captured_at=self.captured_at,source=self.source,
                    source_version=self.source_version,frame_time_sec=self.sec,
                    frame_w=w,frame_h=h,url=f'/api/mosceye/frame.jpg?id={self.id}')


class FrameSource:
    def __init__(self,video):
        self.video=str(video)
        self.lock=threading.RLock()
        self.frames=OrderedDict()
        self.source='footage';self.camera_index=0;self.version=0
        self.playing=True;self.position=5.;self.error=None
        self.closed=threading.Event();self.thread=None
        self.boot=uuid.uuid4().hex[:8];self.counter=0;self.seek=None

    def start(self):
        self.thread=threading.Thread(target=self._produce,daemon=True,name='camera')
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.thread:self.thread.join(timeout=3)

    def configure(self,source,index):
        with self.lock:
            self.source,self.camera_index=source,index
            self.version+=1;self.position=5.;self.seek=5.;self.frames.clear();self.error=None
            self.playing=True
            return self.version

    def play(self,playing=True,seek=None):
        with self.lock:
            self.playing=playing
            if seek is not None:self.seek=seek

    def latest(self,frame_id=None):
        with self.lock:
            if self.error:raise RuntimeError(self.error)
            if frame_id:
                if frame_id not in self.frames:raise ValueError('Ese frame ya expiró. Vuelve a cámara y chequea de nuevo.')
                return self.frames[frame_id]
            if not self.frames:raise RuntimeError(self.error or 'La cámara todavía no entregó un frame.')
            return next(reversed(self.frames.values()))

    def status(self):
        with self.lock:
            return dict(playing=self.playing,playhead_sec=round(self.position,2),
                        camera_error=self.error,source_version=self.version)

    def _produce(self):
        cap=None;opened=None;last=time.monotonic();last_pos=None;black_since=None
        try:
            while not self.closed.is_set():
                start=time.monotonic()
                with self.lock:
                    spec=(self.source,self.camera_index,self.version)
                    playing=self.playing;seek=self.seek;self.seek=None
                try:
                    if opened!=spec:
                        if cap:cap.release()
                        cap=cv2.VideoCapture(self.video if spec[0]=='footage' else spec[1])
                        if not cap.isOpened():raise RuntimeError('No se pudo abrir la fuente. Revisa conexión y permiso de cámara.')
                        opened=spec;last=time.monotonic();last_pos=None;black_since=None
                    if spec[0]=='footage':
                        fps=cap.get(cv2.CAP_PROP_FPS) or 13
                        total=cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps
                        with self.lock:
                            if seek is not None:self.position=min(max(0,seek),max(0,total-1/fps))
                            elif playing:self.position=(self.position+time.monotonic()-last)%total
                            pos=self.position
                        last=time.monotonic()
                        if pos==last_pos and self.frames:
                            self.closed.wait(.08);continue
                        cap.set(cv2.CAP_PROP_POS_MSEC,pos*1000)
                        ok,image=cap.read();last_pos=pos
                        # Container FPS/duration can place the nominal end after
                        # the last decodable frame. Loop immediately instead of
                        # reopening at that same failing seek on every retry.
                        if not ok and pos >= max(0,total-.75):
                            cap.set(cv2.CAP_PROP_POS_MSEC,0)
                            ok,image=cap.read()
                            if ok:
                                pos=last_pos=0.
                                with self.lock:self.position=0.
                    else:
                        ok,image=cap.read();pos=None
                    if not ok:raise RuntimeError('La fuente no entregó imagen. Revisa la cámara e intenta de nuevo.')
                    if spec[0]=='camera' and float(image.mean())<1:
                        black_since=black_since or time.monotonic()
                        if time.monotonic()-black_since>2:raise RuntimeError('La cámara entrega imagen negra. Revisa permisos o la tapa.')
                        self.closed.wait(.1);continue
                    black_since=None
                    ok,jpg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,88])
                    if not ok:raise RuntimeError('No se pudo preparar el frame.')
                    with self.lock:
                        if self.version!=spec[2]:continue
                        self.counter+=1
                        f=Frame(f'{self.boot}-{self.counter}',image,jpg.tobytes(),timestamp(),spec[0],spec[2],pos)
                        self.frames[f.id]=f
                        while len(self.frames)>32:self.frames.popitem(last=False)
                        self.error=None
                except Exception as e:
                    with self.lock:self.error=str(e)
                    if cap:cap.release()
                    cap=None;opened=None
                    self.closed.wait(.5)
                self.closed.wait(max(0,.125-(time.monotonic()-start)))
        finally:
            if cap:cap.release()
