"""Verified Windows tunnel runtime and process-scoped HTTP proxy support."""
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


def configuration(project):
    path = Path(project) / 'environment.local.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    proxy = os.environ.get('ASSISTANT_SHARE_PROXY') or config.get('share_proxy') or urllib.request.getproxies().get('https')
    if proxy:
        address = urllib.parse.urlsplit(proxy)
        if address.scheme not in ('http', 'https') or not address.hostname or address.username or address.password:
            raise ValueError('分享代理须为不含账号密码的 HTTP 地址')
    return config, proxy


def opener_for(proxy):
    return urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy} if proxy else {}))


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_binary(project, cancel, progress):
    project = Path(project)
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('临时分享组件目前支持 Windows x64')
    config, proxy = configuration(project)
    lock = json.loads((project / 'packaging/share-lock.json').read_text(encoding='utf-8'))
    explicit = os.environ.get('ASSISTANT_CLOUDFLARED') or config.get('cloudflared')
    bundled = Path(sys.executable).resolve().parent.parent / 'share/cloudflared.exe'
    path = Path(explicit) if explicit else bundled if bundled.is_file() else project / 'data/share-runtime' / lock['version'] / 'cloudflared.exe'
    if explicit and not path.is_file(): raise ValueError('配置的分享组件不存在，请检查本机环境配置')
    if path.is_file():
        if digest(path) != lock['binary']['sha256']: raise ValueError('分享组件校验不符，请重新准备官方组件')
        return path.resolve(), proxy
    progress('preparing', '首次使用，正在准备分享组件…')
    path.parent.mkdir(parents=True, exist_ok=True)
    for record, target in ((lock['license'], path.with_name('LICENSE')), (lock['binary'], path)):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='download-', suffix='.partial', dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                with opener_for(proxy).open(record['url'], timeout=15) as response:
                    deadline = time.monotonic() + 120
                    while chunk := response.read1(64 * 1024):
                        if cancel.is_set(): raise InterruptedError('已取消分享')
                        if time.monotonic() >= deadline: raise ValueError('分享组件下载超时，请检查网络后重试')
                        stream.write(chunk)
            if digest(temporary) != record['sha256']: raise ValueError('下载的分享组件校验失败')
            if cancel.is_set(): raise InterruptedError('已取消分享')
            if not target.exists() or digest(target) != record['sha256']: temporary.replace(target)
        finally:
            if temporary: temporary.unlink(missing_ok=True)
    return path.resolve(), proxy


class WindowsJob:
    """The OS kills cloudflared if the owning selection service is terminated."""
    def __init__(self, process):
        self.handle = None
        if os.name != 'nt': return
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                        ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t), ('active', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        api.CreateJobObjectW.restype = w.HANDLE
        api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        api.CloseHandle.argtypes = [w.HANDLE]
        handle = api.CreateJobObjectW(None, None)
        limits = Extended(); limits.basic.flags = 0x2000
        if not handle or not api.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not api.AssignProcessToJobObject(handle, w.HANDLE(int(process._handle))):
            error = ctypes.get_last_error()
            if handle: api.CloseHandle(handle)
            raise OSError(error, '无法建立分享进程自动清理保护')
        self.api, self.handle = api, handle

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
