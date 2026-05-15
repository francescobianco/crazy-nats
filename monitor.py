import asyncio
import sys
from datetime import datetime
from nats.aio.client import Client as NATS


async def main():
    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")

    async def handler(msg):
        text = msg.data.decode()
        sys.stdout.write(f"[{datetime.now().isoformat()}] {text}\n")
        sys.stdout.flush()

    await nc.subscribe("room.>", cb=handler)
    sys.stdout.write("Monitor avviato. In ascolto su room.>\n")
    sys.stdout.flush()

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMonitor fermato.")
