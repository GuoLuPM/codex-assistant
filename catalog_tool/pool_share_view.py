"""A public, read-only projection. Never receives a database or owner token."""
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class PublicView:
    def __init__(self, state, pool_root):
        self.share_id = secrets.token_urlsafe(24)
        self.prefix = '/' + secrets.token_urlsafe(32) + '/'
        self.expires_at = time.time() + 240
        self.active = threading.Event()
        self.active.set()
        self.images = {}
        self.items = []
        self.title = state['title']
        root = Path(pool_root).resolve()
        total = 0
        for index, source in enumerate(state['items']):
            public_id = str(index + 1)
            item = {key: source.get(key) for key in ('name', 'model', 'variant', 'features')}
            item.update(id=public_id, image=False, tags=[],
                        prices=[{'label': p['label'], 'value': p['value']} for p in source['prices']])
            if source.get('image'):
                path = root / source['image']
                assets = root / 'assets'
                if not path.resolve().is_relative_to(assets) or any(
                    p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                    for p in (path, *path.parents) if p.is_relative_to(root)
                ): raise ValueError('分享图片路径不在产品图片目录内')
                mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}.get(path.suffix.lower())
                if not mime: raise ValueError('分享图片格式暂不支持')
                total += path.stat().st_size
                if total > 64 * 1024 * 1024: raise ValueError('本页图片超过 64 MB，请减少本次分享的商品')
                self.images[public_id] = (path.read_bytes(), mime)
                item['image'] = True
            self.items.append(item)

    def state(self):
        return {'readonly': True, 'share_id': self.share_id, 'title': self.title, 'state': 'readonly',
                'selected_ids': [], 'revision': 0, 'items': self.items, 'expires_at': self.expires_at}

    def live(self):
        return self.active.is_set() and (self.expires_at is None or time.time() < self.expires_at)


def public_server(view):
    page = Path(__file__).with_name('pool_select.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, status, payload, content_type='application/json; charset=utf-8'):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            for key, value in {'Content-Type': content_type, 'Content-Length': str(len(body)),
                               'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                               'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow, noarchive',
                               'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError): pass

        def do_GET(self):
            if self.path == '/favicon.ico' and self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}':
                return self.reply(204, b'', 'image/x-icon')
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or not self.path.startswith(view.prefix):
                return self.reply(404, {'error': '没有这个分享页面'})
            if not view.live(): return self.reply(410, {'error': '分享已经结束'})
            route = self.path[len(view.prefix):]
            if route == '': return self.reply(200, page, 'text/html; charset=utf-8')
            if route == 'state': return self.reply(200, view.state())
            if route == 'probe': return self.reply(200, {'readonly': True, 'share_id': view.share_id})
            if route.startswith('image/') and route[6:] in view.images:
                data, mime = view.images[route[6:]]
                return self.reply(200, data, mime)
            return self.reply(404, {'error': '没有这个分享资源'})

        def reject_write(self): return self.reply(405, {'error': '这个页面只能查看'})
        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = reject_write

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    return server
