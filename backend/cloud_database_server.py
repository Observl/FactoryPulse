"""Local HTTP entry with SQLite disabled before importing any application code."""
import os
import sqlite3

if os.environ.get('FACTORYPULSE_TEST_ALLOW_ANONYMOUS')=='1':
    raise RuntimeError('网站入口禁止隔离测试数据库模式')


def forbidden_local_database(*args,**kwargs):
    raise RuntimeError('网站只能连接 Cloudflare D1，禁止创建或打开任何本地 SQLite 数据库')


sqlite3.connect=forbidden_local_database
from .main import app  # noqa: E402,F401
