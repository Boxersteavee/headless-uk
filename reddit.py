import datetime
import os
from copy import copy, deepcopy
from pprint import pprint
from typing import Literal, List
from urllib.parse import urlparse

import ojson
import ojson as json
import websockets

import requests

from colors import GREEN, printc, RESET, RED, AQUA
from config import load_config, Config

from dataclasses import dataclass

import time

from now import now


@dataclass
class Coordinates:
    x: int
    y: int
    canvasIndex: int


def ui_to_req_coords(displayX, displayY) -> Coordinates:
    canvasX = (displayX + 500) % 1000
    canvasY = (displayY + 1000) % 1000
    if displayY < 0:
        if displayX < -500:
            canvas = 0
        elif displayX > 499:
            canvas = 2
        else:
            canvas = 1
    else:
        if displayX < -500:
            canvas = 3
        elif displayX > 499:
            canvas = 5
        else:
            canvas = 4
    return Coordinates(canvasX, canvasY, canvas)


colorIndex = 3

VALID_COLORS = ['#6D001A', '#BE0039', '#FF4500', '#FFA800', '#FFD635', '#FFF8B8', '#00A368', '#00CC78', '#7EED56', '#00756F', '#009EAA', '#00CCC0', '#2450A4', '#3690EA', '#51E9F4', '#493AC1', '#6A5CFF', '#94B3FF', '#811E9F', '#B44AC0',
                '#E4ABFF', '#DE107F', '#FF3881', '#FF99AA', '#6D482F', '#9C6926', '#FFB470', '#000000', '#515252', '#898D90', '#D4D7D9', '#FFFFFF'];


def send_request(config: Config, coords: Coordinates, color=3):
    print("got to the reqeust")

    data = f"""{{\"operationName\":\"setPixel\",\"variables\":{{\"input\":{{\"actionName\":\"r/replace:set_pixel\",\"PixelMessageData\":{{\"coordinate\":{{\"x\":{coords.x},\"y\":{coords.y}}},\"colorIndex\":{colorIndex},\"canvasIndex\":{coords.canvasIndex}}}}}}},\"query\":\"mutation setPixel($input: ActInput!) {{\\n  act(input: $input) {{\\n    data {{\\n      ... on BasicMessage {{\\n        id\\n        data {{\\n          ... on GetUserCooldownResponseMessageData {{\\n            nextAvailablePixelTimestamp\\n            __typename\\n          }}\\n          ... on SetPixelResponseMessageData {{\\n            timestamp\\n            __typename\\n          }}\\n          __typename\\n        }}\\n        __typename\\n      }}\\n      __typename\\n    }}\\n    __typename\\n  }}\\n}}\\n\"}}""",

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/114.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "content-type": "application/json",
        "authorization": config.auth_token,
        "apollographql-client-name": "garlic-bread",
        "apollographql-client-version": "0.0.1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site"
    }

    set_pixel = requests.post(config.reddit_uri, data=data, headers=headers)
    print("set pixel", set_pixel.status_code)
    print("set pixel response", set_pixel.text)
    # return data.data.act.data.find((e) => e.data.__typename === 'GetUserCooldownResponseMessageData').data.nextAvailablePixelTimestamp;


def test_authorization(authorization: str) -> bool:
    """ Returns true if the authorization is actually valid
        We could either do this by actually verifying the jwt or by just making a request
        I can't find reddits public key, so I guess we have to just try use it
    """
    return get_nextAvailablePixelTimestamp(authorization) is not None


def get_proxied_url(garlic_url):
    url = urlparse(garlic_url)
    return f"https://garlic-proxy.placenl.nl/{url.path.replace('/media/', '')}?bust={int(time.time() * 1000)}"


async def get_canvas_url(canvas_id: Literal[0, 1, 2, 3, 4, 5]) -> str:
    # todo we can also fetch a new anon token for from reddit because anons can also view the canvas

    # todo we could also have an image class which keeps the socket connection open and updates the differences

    config = load_config(ignore_missing_auth=True)
    printc(f"{now()} {GREEN}Fetching canvas with id: {AQUA}{canvas_id}")

    anon_authorization = get_anon_authorization()

    async with websockets.connect(config.reddit_uri_wss, origin="https://garlic-bread.reddit.com") as websocket:
        connection_init_message = {
            "type": 'connection_init',
            "payload": {
                "Authorization": anon_authorization
            }
        }

        await websocket.send(json.dumps(connection_init_message))

        await websocket.recv()  # This should be {"type":"connection_ack"}

        url_message = {
            "id": "2",
            "type": "start",
            "payload": {
                "variables": {
                    "input": {
                        "channel": {
                            "teamOwner": "GARLICBREAD",
                            "category": "CANVAS",
                            "tag": str(canvas_id)
                        }
                    }
                },
                "extension": {},
                "operationName": "replace",
                "query": "subscription replace($input: SubscribeInput!) { subscribe(input: $input) { id ... on BasicMessage { data { __typename ... on FullFrameMessageData { __typename name timestamp } } __typename } __typename }}"
            }
        }

        await websocket.send(json.dumps(url_message))
        await websocket.recv()  # This is also ack
        result = json.loads(await websocket.recv())  # this is what we want with the link
    match result:
        case {"payload": {"data": {"subscribe": {"data": {"__typename": "FullFrameMessageData", "name": str(canvas_url)}}}}}:
            return canvas_url
        case _:
            raise ValueError(f"Could not fetch canvas with id: {canvas_id}")


class LiveCanvas:
    """ A live connection which updates the same image in memory with the difference, this way we don't have to fetch the whole canvas every time
        todo make this actually work

    """

    def __init__(self, config):
        self.websocket = None
        self.config = config
        self.authorization = get_anon_authorization()

    async def connect(self):
        async with websockets.connect(self.config.reddit_uri_wss, origin="https://garlic-bread.reddit.com") as websocket:
            self.websocket = websocket
            connection_init_message = {
                "type": 'connection_init',
                "payload": {
                    "Authorization": self.authorization
                }
            }

            printc(now(), f"{GREEN} Live canvas connected!")
            await websocket.send(json.dumps(connection_init_message))

            result = await websocket.recv()  # This should be {"type":"connection_ack"}
            printc(now(), f"{GREEN} Live canvas connected!!{RESET}{result}")

            message_id = 2
            for canvas_id in self.config.canvas_indexes:
                url_message = {
                    "id": str(message_id),
                    "type": "start",
                    "payload": {
                        "variables": {
                            "input": {
                                "channel": {
                                    "teamOwner": "GARLICBREAD",
                                    "category": "CANVAS",
                                    "tag": str(canvas_id)
                                }
                            }
                        },
                        "extension": {},
                        "operationName": "replace",
                        "query": "subscription replace($input: SubscribeInput!) { subscribe(input: $input) { id ... on BasicMessage { data { __typename ... on FullFrameMessageData { __typename name timestamp } } __typename } __typename }}"
                    }
                }
                message_id += 1
                await websocket.send(json.dumps(url_message))

            async for message in self.websocket:
                print("GOT:", message)


def get_place_cooldown(authorization: str) -> int | None:
    next_time = get_nextAvailablePixelTimestamp(authorization)
    if next_time is None:
        return None
    diff = next_time - time.time() / 1000
    return int(max((diff, 0)))


def get_nextAvailablePixelTimestamp(authorization) -> int | None:
    if not authorization:
        return None

    headers = {
        'content-type': 'application/json',
        'authorization': authorization,
        'apollographql-client-name': 'garlic-bread',
        'apollographql-client-version': '0.0.1',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site'
    }

    payload = {
        'query': 'mutation GetPersonalizedTimer{\n  act(\n    input: {actionName: "r/replace:get_user_cooldown"}\n  ) {\n    data {\n      ... on BasicMessage {\n        id\n        data {\n          ... on GetUserCooldownResponseMessageData {\n            nextAvailablePixelTimestamp\n          }\n        }\n      }\n    }\n  }\n}\n\n\nsubscription SUBSCRIBE_TO_CONFIG_UPDATE {\n  subscribe(input: {channel: {teamOwner: GARLICBREAD, category: CONFIG}}) {\n    id\n    ... on BasicMessage {\n      data {\n        ... on ConfigurationMessageData {\n          __typename\n          colorPalette {\n            colors {\n              hex\n              index\n            }\n          }\n          canvasConfigurations {\n            dx\n            dy\n            index\n          }\n          canvasWidth\n          canvasHeight\n        }\n      }\n    }\n  }\n}\n\n\nsubscription SUBSCRIBE_TO_CANVAS_UPDATE {\n  subscribe(\n    input: {channel: {teamOwner: GARLICBREAD, category: CANVAS, tag: "0"}}\n  ) {\n    id\n    ... on BasicMessage {\n      id\n      data {\n        __typename\n        ... on DiffFrameMessageData {\n          currentTimestamp\n          previousTimestamp\n          name\n        }\n        ... on FullFrameMessageData {\n          __typename\n          name\n          timestamp\n        }\n      }\n    }\n  }\n}\n\n\n\n\nmutation SET_PIXEL {\n  act(\n    input: {actionName: "r/replace:set_pixel", PixelMessageData: {coordinate: { x: 53, y: 35}, colorIndex: 3, canvasIndex: 0}}\n  ) {\n    data {\n      ... on BasicMessage {\n        id\n        data {\n          ... on SetPixelResponseMessageData {\n            timestamp\n          }\n        }\n      }\n    }\n  }\n}\n\n\n\n\n# subscription configuration($input: SubscribeInput!) {\n#     subscribe(input: $input) {\n#       id\n#       ... on BasicMessage {\n#         data {\n#           __typename\n#           ... on RReplaceConfigurationMessageData {\n#             colorPalette {\n#               colors {\n#                 hex\n#                 index\n#               }\n#             }\n#             canvasConfigurations {\n#               index\n#               dx\n#               dy\n#             }\n#             canvasWidth\n#             canvasHeight\n#           }\n#         }\n#       }\n#     }\n#   }\n\n# subscription replace($input: SubscribeInput!) {\n#   subscribe(input: $input) {\n#     id\n#     ... on BasicMessage {\n#       data {\n#         __typename\n#         ... on RReplaceFullFrameMessageData {\n#           name\n#           timestamp\n#         }\n#         ... on RReplaceDiffFrameMessageData {\n#           name\n#           currentTimestamp\n#           previousTimestamp\n#         }\n#       }\n#     }\n#   }\n# }\n',
        'variables': {
            'input': {
                'channel': {
                    'teamOwner': 'GARLICBREAD',
                    'category': 'R_REPLACE',
                    'tag': 'canvas:0:frames'
                }
            }
        },
        'operationName': 'GetPersonalizedTimer',
        'id': None
    }

    response = requests.post('https://gql-realtime-2.reddit.com/query', json=payload, headers=headers)
    print(response.status_code, response.text)

    data = response.json()

    if not data.get('data'):
        return None

    ts = data['data']['act']['data'][0]['data']['nextAvailablePixelTimestamp']

    return 1 if not ts else ts


def get_new_anon_session() -> dict:
    printc(f"{now()} {GREEN}Fetching new anon access token from {RED}reddit{GREEN}, this may take a bit")
    response = requests.get('https://reddit.com/r/place',
                            headers={
                                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/116.0'
                            })
    body = response.text

    # todo: yuck
    configRaw = body.split('<script id="data">window.___r = ')[1].split(';</script>')[0]
    parsed_config = json.loads(configRaw)

    auth_session = {"accessToken": "Bearer " + copy(parsed_config['user']['session']['accessToken']), "expires_at": parsed_config['user']['session']['expiresIn'] + int(time.time())}  # copy the user_session, so we can delete the big object

    del parsed_config  # delete the big session dict

    return auth_session


@dataclass
class RedditSession:
    accessToken: str
    expires_at: int

    @staticmethod
    def from_dict(payload) -> "RedditSession":
        match payload:
            case {"accessToken": str(accessToken), "expires_at": int(expires_at)} | {"accessToken": str(accessToken), "expires_at": float(expires_at)}:
                return RedditSession(accessToken, expires_at)
            case _:
                raise ValueError("Could not parse reddit session from dict!")

    def save_to_file(self):
        printc(now(), f"{GREEN}Writing reddit session to {AQUA}reddit_session.json!")
        with open('reddit_session.json', 'w+') as reddit_session:
            ojson.dump({"accessToken": self.accessToken, "expires_at": self.expires_at}, reddit_session, indent=2)

    @staticmethod
    def load_from_file() -> "RedditSession":
        printc(now(), f"{GREEN}Reading reddit session from {AQUA}reddit_session.json!")
        with open('reddit_session.json', 'r') as reddit_session_file:
            reddit_session = ojson.load(reddit_session_file)
            return RedditSession.from_dict(reddit_session)


__reddit_session: RedditSession | None = None


def get_anon_session() -> RedditSession:
    global __reddit_session

    if not __reddit_session and os.path.exists("reddit_session.json"):
        # first read try the session from the file
        try:
            __reddit_session = RedditSession.load_from_file()
        except ValueError:  # if we can't read from the file get a new session
            printc(now(), RED + "Could not parse reddit session from file, fetching again")

            __reddit_session = RedditSession.from_dict(get_new_anon_session())
            __reddit_session.save_to_file()

    elif not __reddit_session:
        __reddit_session = RedditSession.from_dict(get_new_anon_session())
        __reddit_session.save_to_file()

    # Check if the session is still valid, if we already fetched again it should be still valid
    if time.time() > __reddit_session.expires_at:
        printc(now(), RED + "Reddit session is expired fetching a new one!")
        __reddit_session = RedditSession.from_dict(get_new_anon_session())
        __reddit_session.save_to_file()

    return __reddit_session


def get_anon_authorization() -> str:
    """
    :return:  A Bearer ... jwt
    """
    return get_anon_session().accessToken