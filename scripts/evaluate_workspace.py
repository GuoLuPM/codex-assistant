"""Opt-in isolated model exercise; transient threads and synthetic materials only."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.workspace_rehearsal import rehearsal_workspace


CASES = {
    'gift': ['这份报价加进去。帮我挑零售价一百以内、送同事拿得出手的小礼物，让我自己选。'],
    'duplicate': ['这份报价可能以前给过你，重复的别再加。看看零售价一百块以内、送同事的礼盒有哪些，让我自己选。'],
    'refine': ['找些零售价一百块以内送同事的礼盒。', '食品先不要了，其他要求照旧，让我选。'],
    'help': ['我不会用，先带我一步一步来。'],
    'general': ['帮我把这句话整理成一份简短通知：周五下午两点到会议室开会，带上上周的销售记录。'],
}


async def evaluate(directory, profile, case, source=None):
    async with rehearsal_workspace(directory) as service:
        task = service.store.create('合成模型验收', profile=profile)
        tid = task['task_id']; inputs = []
        if source:
            source = Path(source)
            async def chunks():
                with source.open('rb') as stream:
                    while block := stream.read(65536): yield block
            inputs = [(await service.upload(tid, chunks(), source.name))['input_id']]
        start = time.monotonic(); turns = []
        for i, text in enumerate(CASES[case]):
            task = service.store.snapshot(tid)
            receipt = await service.message(tid, {'request_id': 'eval-' + str(i), 'expected_revision': task['revision'],
                                                 'text': text, 'input_ids': inputs if i == 0 else []})
            async with asyncio.timeout(300):
                while True:
                    task = service.store.snapshot(tid)
                    if task['state'] != 'running': break
                    await asyncio.sleep(.5)
            turns.append({'state': task['state'], 'receipt': receipt['state']})
            if task['state'] not in ('ready', 'completed'): break
        await service.runtime.verify_history()
        result = {'profile': profile, 'case': case, 'task_id': tid, 'seconds': round(time.monotonic()-start, 2),
            'directory': str(service.project), 'not_in_native_history': True,
            'ok': len(turns) == len(CASES[case]) and all(t['state'] in ('ready', 'completed') and t['receipt'] != 'failed' for t in turns),
            'turns': turns, 'usage': service.store.usage(task['thread_id']) if task.get('thread_id') else None,
            'artifacts': task['artifact_ids'], 'selections': [b['body'] for b in task['blocks'] if b['kind'] == 'products'],
            'reply': [b['body']['text'] for b in task['blocks'] if b['kind'] == 'text' and b['body']['role'] == 'assistant' and b['body'].get('phase') != 'commentary'],
            'pending_questions': task['pending_requests']}
        (service.project / 'result.local.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return {k: result[k] for k in ('ok', 'profile', 'case', 'task_id', 'directory', 'not_in_native_history', 'seconds', 'turns', 'usage', 'artifacts', 'reply')}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--profile', choices=['normal', 'low'], default='normal')
    p.add_argument('--case', choices=CASES, required=True)
    p.add_argument('--source', type=Path)
    a = p.parse_args(argv)
    result = asyncio.run(evaluate(a.work_dir, a.profile, a.case, a.source))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
