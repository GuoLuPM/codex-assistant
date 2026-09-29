"""Lifecycle of one temporary read-only share, owned by a local selection service."""
import threading
import time
from pathlib import Path

from pool_share_view import public_server
from pool_tunnel import open_tunnel, probe_public


def validate_minutes(minutes):
    if minutes is not None and (type(minutes) is not int or not 1 <= minutes <= 525600):
        raise ValueError('请填写有效时长，或选择永久')


class ShareManager:
    def __init__(self, project, directory, tunnel_factory=open_tunnel, probe=probe_public):
        self.project, self.directory = Path(project), Path(directory)
        self.tunnel_factory, self.probe = tunnel_factory, probe
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.worker = self.view = None
        self.result = {'status': 'idle', 'message': ''}

    def state(self):
        with self.lock: return dict(self.result)

    def busy(self):
        return bool(self.worker and self.worker.is_alive())

    def progress(self, status, message):
        with self.lock:
            if not self.cancel.is_set(): self.result = {'status': status, 'message': message}

    def start(self, view, minutes=None):
        validate_minutes(minutes)
        with self.lock:
            if self.busy(): return dict(self.result)
            self.cancel = threading.Event()
            self.view = view
            self.view.expires_at = time.time() + 300
            self.result = {'status': 'preparing', 'message': '正在生成链接…'}
            self.worker = threading.Thread(target=self._run, args=(view, minutes), daemon=True)
            self.worker.start()
            return dict(self.result)

    def _run(self, view, minutes):
        server = serving = None
        outcome = {'status': 'stopped', 'message': '已停止分享'}
        try:
            server = public_server(view)
            serving = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
            serving.start()
            target = f'http://127.0.0.1:{server.server_port}'
            with self.tunnel_factory(target, self.project, self.directory, self.cancel, self.progress) as (host, process, proxy):
                url = host + view.prefix
                self.progress('checking', '正在生成链接…')
                deadline = time.monotonic() + 65
                while not self.cancel.is_set():
                    if process.poll() is not None: raise ValueError('分享连接中断了，请重新分享')
                    if self.probe(url, view.share_id, proxy): break
                    if time.monotonic() >= deadline: raise ValueError('外网访问验证未通过，请检查网络后重试')
                    self.cancel.wait(1)
                if self.cancel.is_set(): return
                view.expires_at = None if minutes is None else time.time() + minutes * 60
                with self.lock:
                    if self.cancel.is_set(): return
                    self.result = {'status': 'ready', 'message': '链接已生成', 'url': url,
                                   'expires_at': view.expires_at, 'minutes': minutes}
                while not self.cancel.wait(.2):
                    if view.expires_at is not None and time.time() >= view.expires_at:
                        outcome = {'status': 'expired', 'message': '分享已到期'}
                        break
                    if process.poll() is not None: raise ValueError('分享连接中断了，请重新分享')
        except InterruptedError:
            pass
        except Exception as error:
            # Keep details local; the browser gets a short actionable message.
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / 'share-error.log').write_text(str(error), encoding='utf-8')
            outcome = {'status': 'failed', 'message': str(error) if isinstance(error, ValueError) else '暂时没连上分享服务，请检查网络后重试'}
        finally:
            view.active.clear()
            if server: server.shutdown();server.server_close()
            if serving: serving.join(timeout=2)
            with self.lock:
                if self.cancel.is_set(): outcome = {'status': 'stopped', 'message': '已停止分享'}
                self.result = outcome

    def stop(self):
        with self.lock:
            if not self.busy(): return dict(self.result)
            self.cancel.set()
            if self.view: self.view.active.clear()
            self.result = {'status': 'stopping', 'message': '正在停止分享…'}
            return dict(self.result)

    def close(self):
        self.stop()
        if self.worker: self.worker.join(timeout=20)
        if self.busy(): raise RuntimeError('Sharing cleanup did not finish')
