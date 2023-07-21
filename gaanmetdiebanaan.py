import time

import reddit
from client import Client
from config import load_config, Config
import asyncio

from now import now
from reddit import Coordinates


async def main():
    config = load_config()
    # make client
    client = Client(config)

    while True:
        try:
            await client.connect()
        except TimeoutError:
            print(f"{now()} We got disconnected. Lets try connect again in 4 seconds")
            if client.place_timer:
                client.place_timer.cancel()
            if client.pong_timer:
                client.pong_timer.cancel()
            time.sleep(4)
        else:  # If another error happened then just let it die
            break


def gaan():
    # config = load_config()
    # coords = Coordinates(3, 600, 1)
    # reddit.place_pixel(config, coords, 3)

    asyncio.get_event_loop().run_until_complete(main())


if __name__ == '__main__':
    gaan()
