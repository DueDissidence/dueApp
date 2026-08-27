from app import stream_list_pb2_grpc, stream_list_pb2
from pathlib import Path
import threading
import logging
import fastapi
import httpx
import time
import grpc
import os


APP_ENV = os.getenv("APP_ENV", "development").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger("backend")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger.handlers.clear()

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

if APP_ENV == "production":
    log_path = Path("/tmp/logs")
    log_path.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path / "app.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
else:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Parameters for GET request
url = "https://rumble.com/-livestream-api/get-data"
headers = {'Accept': "application/json", "User-Agent": "Mozilla/5.0"}

app = fastapi.FastAPI()

def parse_livestream(data, code):
    livestream = {
        'rants': [],
        'watching': 0,
        'likes': 0,
        'title': "No Livestream Found",
        'status': code
    }

    if data is not None:
        data = data.get('livestreams')
        if data:
            data = data[0]
            data['chat']['recent_rants'].reverse()
            livestream['rants'] = data['chat']['recent_rants']
            livestream['likes'] = data['likes']
            livestream['watching'] = data['watching_now']
            livestream['title'] = data['title']

    return livestream


@app.get("/rants")
async def rants() -> dict:
    data = None
    code = 200
    # Sending GET request
    async with httpx.AsyncClient(headers=headers) as client:
        try:
            response = await client.get(
                url, params={"key": os.environ['RUMBLE_KEY']})
            code = response.status_code
            if code == 200:
                data = response.json()
        except httpx.ConnectTimeout:
            pass

    livestream = parse_livestream(data, code)
    return livestream


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class SuperchatManager:
    def __init__(self, youtube_api_key: str, youtube_channel_id: str):
        self.youtube_api_key = youtube_api_key
        self.youtube_channel_id = youtube_channel_id

        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.started = False
        self.current_live_chat_id: str | None = None
        self.superchats: list[dict] = []

    async def get_live_chat_id(self) -> str | None:
        params = {
            "part": "id",
            "channelId": self.youtube_channel_id,
            "type": "video",
            "maxResults": 1,
            "key": self.youtube_api_key,
        }

        items = []
        for event_type in ["live", "upcoming"]:
            params["eventType"] = event_type

            async with httpx.AsyncClient() as client:
                resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        break
                    logger.info("YouTube no stream with event type: %s", event_type)
                else:
                    logger.info(
                        "YouTube livestream search failed: %s %s %s",
                        resp.status_code,
                        event_type,
                        resp.text,
                    )
                    return None

        if not items:
            logger.info("No livestream found")
            return None

        video_id = items[0].get("id", {}).get("videoId")
        params = {
            "part": "liveStreamingDetails",
            "id": video_id,
            "key": self.youtube_api_key,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(YOUTUBE_VIDEOS_URL, params=params)
            if resp.status_code != 200:
                logger.info(
                    "YouTube video search failed: %s %s",
                    resp.status_code,
                    resp.text,
                )
                return None
            videos_data = resp.json()

        v_items = videos_data.get("items", [])
        if not v_items:
            logger.info("No video details found")
            return None

        live_details = v_items[0].get("liveStreamingDetails", {})
        live_chat_id = live_details.get("activeLiveChatId")
        if not live_chat_id:
            logger.info("No livechat found on video")
            return None

        return live_chat_id

    def _reset_state(self) -> None:
        with self.lock:
            self.started = False
            self.current_live_chat_id = None
            self.superchats = []
            self.thread = None

    def _append_superchat(self, msg) -> None:
        snippet = msg.snippet

        if snippet.type not in [15, 16, 18]:
            return

        if snippet.type == 15:
            sc = snippet.super_chat_details
            message = sc.user_comment
        elif snippet.type == 16:
            sc = snippet.super_sticker_details
            message = "Super Sticker"
        elif snippet.type == 18:
            sc = snippet.membership_gifting_details
            message = f"{sc.gift_memberships_count} Gifted Membership(s)"
        else:
            sc = snippet
            message = snippet.display_message

        author = msg.author_details

        superchat = {
            "id": msg.id,
            "author": author.display_name,
            "authorChannelId": snippet.author_channel_id,
            "profileImageUrl": author.profile_image_url,
            "message": message,
            "amountMicros": getattr(sc, 'amount_micros', 0),
            "amountDisplayString": getattr(sc, 'amount_display_string', '0'),
            "currency": getattr(sc, 'currency', '$'),
            "tier": getattr(sc, 'tier', 'A'),
            "publishedAt": snippet.published_at,
        }

        self.superchats.append(superchat)

    def _run_superchat_stream(self, live_chat_id: str) -> None:
        creds = grpc.ssl_channel_credentials()

        try:
            with grpc.secure_channel("dns:///youtube.googleapis.com:443", creds) as channel:
                stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)
                metadata = (("x-goog-api-key", self.youtube_api_key),)

                next_page_token = ""
                while True:
                    request = stream_list_pb2.LiveChatMessageListRequest(
                        part=["snippet", "authorDetails"],
                        live_chat_id=live_chat_id,
                        max_results=200,
                        page_token=next_page_token,
                    )

                    try:
                        stream_ended = False

                        for response in stub.StreamList(request, metadata=metadata):

                            if getattr(response, "offline_at", None):
                                logger.info(
                                    "YouTube live chat went offline at %s",
                                    response.offline_at,
                                )
                                stream_ended = True
                                break

                            for msg in response.items:
                                self._append_superchat(msg)

                            next_page_token = response.next_page_token or ""

                        if stream_ended:
                            break

                    except grpc.RpcError as e:
                        if e.code() == grpc.StatusCode.UNAVAILABLE:
                            time.sleep(10)
                            continue

                        logger.info("gRPC stream ended with error: %s", e)
                        break

        finally:
            self._reset_state()
            logger.info("Superchat streaming thread stopped.")

    async def ensure_stream_started(self) -> None:
        logger.info("Entering ensure_stream_started")

        with self.lock:
            if self.started:
                logger.info("Superchat thread already started.")
                return

        live_chat_id = await self.get_live_chat_id()
        if not live_chat_id:
            logger.info("No active YouTube live chat; superchat stream not started.")
            return

        with self.lock:
            if self.started:
                logger.info("Superchat thread already started after lookup.")
                return

            self.current_live_chat_id = live_chat_id
            logger.info("current_live_chat_id set to %s", self.current_live_chat_id)

            thread = threading.Thread(
                target=self._run_superchat_stream,
                args=(live_chat_id,),
                daemon=True,
            )
            thread.start()

            self.thread = thread
            self.started = True
            logger.info("Superchat streaming thread started.")

    def get_status(self) -> dict:
        with self.lock:
            return {
                "status": 200,
                "liveChatId": self.current_live_chat_id,
                "started": self.started,
            }

    def get_superchats_payload(self) -> dict:
        return {
            "status": 200,
            "superchats": list(self.superchats),
        }


superchat_manager = SuperchatManager(
    youtube_api_key=os.environ["YOUTUBE_KEY"],
    youtube_channel_id=os.environ["YOUTUBE_CHANNEL_ID"],
)

logger.info("YouTube Channel ID: %s", os.environ["YOUTUBE_CHANNEL_ID"])

@app.get("/youtube/streamid")
async def youtube_get_stream_id() -> dict:
    await superchat_manager.ensure_stream_started()
    result = superchat_manager.get_status()
    logger.info("youtube_get_stream_id response: %s", result)
    return result


@app.get("/youtube/superchats")
async def youtube_superchats() -> dict:
    return superchat_manager.get_superchats_payload()