"""python examples/sdk.py /allowed/local/root"""
import asyncio
import sys
from remote_fs_browser import Browser, Policy


async def main(root):
    async with Browser(Policy(local_roots=[root])) as browser:
        async with await browser.connect({'type': 'local', 'root': root}) as session:
            print(await session.list('/'))
            print(session.descriptor('/'))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
