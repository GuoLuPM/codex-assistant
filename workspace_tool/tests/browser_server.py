"""Disposable browser fixture: real HTTP/store/pool, no model or external sharing."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from workspace_tool.app import create_app
from workspace_tool.auth import LocalAuth, digest
from workspace_tool.service import Workspace
from workspace_tool.tests.test_service import FakeRuntime
from workspace_tool.views import build_view
from workspace_tool.pool_adapter import Pool, Selections


async def main():
    import uvicorn
    from openpyxl import Workbook
    private = ROOT / 'data/browser-checks'
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='assistant-browser-', dir=private) as directory:
        root = Path(directory); host = '127.0.0.1:' + os.environ.get('ASSISTANT_TEST_PORT', '51937')
        service = Workspace(root, host, project=root, runtime=FakeRuntime())
        book = Workbook(); book.active.append(['名称', '型号', '零售价', '功能特点'])
        book.active.append(['出门带着用的保温杯礼盒', 'C-500', 88, '容量500ml，礼盒包装。合成测试资料。'])
        book.active.append(['茶香礼盒', 'T-100', 68, '乌龙茶组合，礼盒包装。合成测试资料。'])
        book.save(root / 'synthetic.xlsx')
        task = service.store.create('给同事的礼品')
        tid = task['task_id']
        service.store.record(tid, 'user_message', {'block_id': 'u1', 'text': '帮我找一百元以内的礼盒。'})
        pool = Pool(service.pool.root)
        pool.add(root / 'synthetic.xlsx')
        choices = Selections(pool)
        sid = choices.create([p['id'] for p in pool.search()['items']], ['retail_price'], '给同事的礼品')['session_id']
        pool.close()
        service.store.add_ref(tid, 'session', sid, {'session_id': sid})
        service.store.record(tid, 'block', build_view(tid, {'kind': 'products', 'refs': {'session_id': sid}}, service.store, service.pool))
        async def interrupted_export(task_id, session_id, revision, request_id):
            # Exercise the real sealed-selection lifecycle without PPT dependencies.
            db = Pool(service.pool.root)
            try: Selections(db).seal(session_id)
            finally: db.close()
            await asyncio.Future()
        service.pool.export = interrupted_export
        auth = LocalAuth(host)
        # The fixed bootstrap value exists only in this synthetic test process.
        auth._starts[digest('browser-fixture')] = auth.clock() + 3600
        app = create_app(service, auth, ROOT / 'workspace_tool/web/dist')
        await uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=int(host.split(':')[1]), log_level='warning', access_log=False)).serve()


if __name__ == '__main__': asyncio.run(main())
