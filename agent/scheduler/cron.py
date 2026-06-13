from __future__ import annotations

import asyncio
import logging

from agent.scheduler.service import scheduler_service

logger = logging.getLogger(__name__)


async def main() -> None:
    await scheduler_service.start()
    logger.info("Scheduler démarré (mode standalone)")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        await scheduler_service.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
