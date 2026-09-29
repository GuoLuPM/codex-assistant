"""Cloudflare Quick Tunnel adapter. No owner endpoints ever enter its origin."""
import collections
import contextlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from share_runtime import WindowsJob, opener_for, prepare_binary


def api_relay(proxy, cancel):
    # Upstream's Quick Tunnel HTTP client does not use ProxyFromEnvironment.
    # Its documented quick-service option lets this bounded local relay apply
    # a scoped proxy to provisioning. Edge traffic still requires outbound access.
    prefix = '/' + secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            if cancel.is_set() or self.path != prefix + '/tunnel' or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                self.send_error(404);return
            try:
                if int(self.headers.get('Content-Length', '0')) != 0: self.send_error(400);return
                request = urllib.request.Request('https://api.trycloudflare.com/tunnel', data=b'', headers={
                    'Content-Type': 'application/json', 'User-Agent': 'codex-assistant-temporary-share'})
                with opener_for(proxy).open(request, timeout=12) as response:
                    body = response.read(1024 * 1024 + 1)
                    if len(body) > 1024 * 1024: raise ValueError('Oversized provisioning response')
                self.send_response(200);self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)));self.end_headers();self.wfile.write(body)
            except (OSError, ValueError): self.send_error(502, 'Tunnel provisioning unavailable')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
    thread.start()
    return server, thread, f'http://127.0.0.1:{server.server_port}{prefix}'


@contextlib.contextmanager
def open_tunnel(target, project, directory, cancel, progress):
    binary, proxy = prepare_binary(project, cancel, progress)
    if cancel.is_set(): raise InterruptedError('已取消分享')
    directory = Path(directory);directory.mkdir(parents=True, exist_ok=True)
    config = directory / 'share-tunnel.local.json'
    config.write_text('{}\n', encoding='utf-8')  # JSON is also valid YAML; ignore personal tunnel configuration.
    relay, relay_thread, service = api_relay(proxy, cancel)
    process = job = reader = None
    lines = collections.deque(maxlen=80)
    try:
        environment = {k: v for k, v in os.environ.items() if not k.startswith(('TUNNEL_', 'CLOUDFLARE_'))}
        command = [str(binary), 'tunnel', '--config', str(config), '--no-autoupdate', '--protocol', 'http2',
                   '--quick-service', service, '--url', target, '--http-host-header', target.removeprefix('http://')]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', env=environment,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        job = WindowsJob(process)
        def read():
            for line in process.stdout: lines.append(line.rstrip()[:1500])
        reader = threading.Thread(target=read, daemon=True);reader.start()
        progress('connecting', '正在连接临时分享服务…')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not cancel.wait(.15):
            if process.poll() is not None: raise ValueError('临时链接申请失败，请检查网络和代理后重试')
            matches = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com\b', '\n'.join(list(lines)))
            if matches:
                yield matches[0], process, proxy
                return
        if cancel.is_set(): raise InterruptedError('已取消分享')
        raise ValueError('临时分享连接超时，请检查网络后重试')
    finally:
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=3)
        if job: job.close()
        if reader: reader.join(timeout=2)
        if process and process.stdout: process.stdout.close()
        relay.shutdown();relay.server_close();relay_thread.join(timeout=2)
        (directory / 'share.log').write_text('\n'.join(list(lines)), encoding='utf-8')


def probe_public(url, share_id, proxy):
    try:
        with opener_for(proxy).open(url + 'probe', timeout=6) as response:
            if response.geturl() != url + 'probe': return False
            body = json.loads(response.read(4096))
            return body.get('readonly') is True and body.get('share_id') == share_id
    except (OSError, ValueError): return False
