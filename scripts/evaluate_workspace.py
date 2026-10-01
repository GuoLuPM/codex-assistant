"""Opt-in live model exercise; private evidence, native counters, no token estimates."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workspace_tool.cli import control
from workspace_tool.tasks import TaskStore


CASES = {
    'gift': ['这份报价加进去。帮我挑零售价一百以内、送同事拿得出手的小礼物，让我自己选。'],
    'duplicate': ['这份报价可能以前给过你，重复的别再加。看看零售价一百块以内、送同事的礼盒有哪些，让我自己选。'],
    'refine': ['找些零售价一百块以内送同事的礼盒。', '食品先不要了，其他要求照旧，让我选。'],
    'help': ['我不会用，先带我一步一步来。'],
    'general': ['帮我把这句话整理成一份简短通知，存成文本给我：周五下午两点到会议室开会，带上上周的销售记录。'],
}


def evaluate(directory, profile, case, source=None):
    directory = Path(directory).resolve()
    registration = json.loads((directory / 'server.local.json').read_text(encoding='utf-8'))
    opened = control(registration, 'open', method='POST')
    origin = registration['origin']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
    def call(path, data=None, *, raw=None, name=None):
        headers = {'Origin': origin, 'Content-Type': 'application/json'}
        if raw is not None:
            from urllib.parse import quote
            headers.update({'Content-Type': 'application/octet-stream', 'X-File-Name': quote(name)})
        payload = raw if raw is not None else json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        request = urllib.request.Request(origin + path, data=payload, headers=headers)
        with opener.open(request, timeout=120) as response: return json.load(response)
    from urllib.parse import parse_qs, urlsplit
    call('/api/bootstrap', {'token': parse_qs(urlsplit(opened['url']).fragment)['start'][0]})
    task = call('/api/tasks', {'model_profile': profile})
    tid = task['task_id']; inputs = []
    if source:
        source = Path(source)
        inputs = [call('/api/tasks/' + tid + '/inputs', raw=source.read_bytes(), name=source.name)['input_id']]
    start = time.monotonic(); turns = []
    for i, text in enumerate(CASES[case]):
        task = call('/api/tasks/' + tid)
        receipt = call('/api/tasks/' + tid + '/messages', {'request_id': 'eval-' + str(i), 'expected_revision': task['revision'], 'text': text, 'input_ids': inputs if i == 0 else []})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            task = call('/api/tasks/' + tid)
            if task['state'] not in ('running',): break
            time.sleep(1)
        else: raise ValueError('Evaluation timed out; task remains available in the workspace')
        turns.append({'state': task['state'], 'receipt': receipt['state']})
        if task['state'] != 'ready' and task['state'] != 'completed': break
    store = TaskStore(directory / 'workspace.sqlite3')
    result = {'profile': profile, 'case': case, 'task_id': tid, 'seconds': round(time.monotonic()-start, 2),
        'turns': turns, 'usage': store.usage(task['thread_id']) if task.get('thread_id') else None,
        'artifacts': task['artifact_ids'], 'selections': [b['body'] for b in task['blocks'] if b['kind'] == 'products'],
        'reply': [b['body']['text'] for b in task['blocks'] if b['kind'] == 'text' and b['body']['role'] == 'assistant' and b['body'].get('phase') != 'commentary'],
        'pending_questions': task['pending_requests']}
    destination = ROOT / 'data/workspace-evaluation'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / (tid + '.local.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return {k: result[k] for k in ('profile', 'case', 'task_id', 'seconds', 'turns', 'usage', 'artifacts', 'reply')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--profile', choices=['normal', 'low'], default='normal')
    p.add_argument('--case', choices=CASES, required=True)
    p.add_argument('--source', type=Path)
    a = p.parse_args()
    print(json.dumps(evaluate(a.work_dir, a.profile, a.case, a.source), ensure_ascii=False))
