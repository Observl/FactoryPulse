"""Bound DNS checks without blocking the application's async request loop."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from fastapi import HTTPException

class AddressValidationPool:
    def __init__(self,workers=2,timeout=5):
        self.executor=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='factorypulse-ai-address')
        self.slots=BoundedSemaphore(workers)
        self.timeout=timeout

    async def check(self,address,validator):
        if not self.slots.acquire(blocking=False):
            raise HTTPException(503,'AI连接检查繁忙，请稍后重试；设备查询和人工维护仍可使用')
        try: future=self.executor.submit(validator,address)
        except BaseException:
            self.slots.release()
            raise
        # A timeout cannot interrupt the OS resolver. Keep its slot until it really ends.
        future.add_done_callback(lambda _:self.slots.release())
        try: return await asyncio.wait_for(asyncio.wrap_future(future),timeout=self.timeout)
        except TimeoutError:
            raise HTTPException(504,'AI地址解析超时，请检查网络；设备查询和人工维护仍可使用')

    def close(self): self.executor.shutdown(wait=True,cancel_futures=True)

address_validation=AddressValidationPool()
