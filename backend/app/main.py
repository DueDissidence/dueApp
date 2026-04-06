from app import stream_list_pb2_grpc, stream_list_pb2
import threading
import datetime
import fastapi
import httpx
import time
import grpc
import os


# Parameters for GET request
url = "https://rumble.com/-livestream-api/get-data"
headers = {'Accept': "application/json", "User-Agent": "Mozilla/5.0"}

app = fastapi.FastAPI()
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_API_KEY = os.environ["YOUTUBE_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
SUPERCHAT_THREAD_STARTED = False
LIVE_CHAT_CLEAR_TIMER = None
SUPERCHAT_THREAD_LOCK = threading.Lock()
CURRENT_LIVE_CHAT_ID: str | None = None
SUPERCHATS: list[dict] = []


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


async def get_live_chat_id(channel_id: str) -> str | None:
    search_params = {
        "part": "id",
        "channelId": channel_id,
        "eventType": "live",
        "type": "video",
        "maxResults": 1,
        "key": YOUTUBE_API_KEY,
    }

    async with httpx.AsyncClient() as client:
        search_resp = await client.get(YOUTUBE_SEARCH_URL, params=search_params)
        if search_resp.status_code != 200:
            print("search.list error", search_resp.status_code, search_resp.text)
            return None
        search_data = search_resp.json()

    items = search_data.get("items", [])
    if not items:
        search_params["eventType"] = "upcoming"

        async with httpx.AsyncClient() as client:
            search_resp = await client.get(YOUTUBE_SEARCH_URL, params=search_params)
            if search_resp.status_code != 200:
                print("search.list error", search_resp.status_code, search_resp.text)
                return None
            search_data = search_resp.json()

        items = search_data.get("items", [])
        if not items:
            print("No live video found for channel.")
            return None

    video_id = items[0].get("id", {}).get("videoId")
    videos_params = {
        "part": "liveStreamingDetails",
        "id": video_id,
        "key": YOUTUBE_API_KEY,
    }

    async with httpx.AsyncClient() as client:
        videos_resp = await client.get(YOUTUBE_VIDEOS_URL, params=videos_params)
        if videos_resp.status_code != 200:
            print("videos.list error", videos_resp.status_code, videos_resp.text)
            return None
        videos_data = videos_resp.json()

    v_items = videos_data.get("items", [])
    if not v_items:
        print("No video details returned.")
        return None

    live_details = v_items[0].get("liveStreamingDetails", {})
    live_chat_id = live_details.get("activeLiveChatId")
    if not live_chat_id:
        print("No activeLiveChatId on video.")
        return None

    return live_chat_id


def get_superchats(live_chat_id: str) -> None:
    if not live_chat_id:
        print("No live_chat_id provided; exiting.")
        return

    creds = grpc.ssl_channel_credentials()
    with grpc.secure_channel("dns:///youtube.googleapis.com:443", creds) as channel:
        stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)
        metadata = (("x-goog-api-key", YOUTUBE_API_KEY),)

        next_page_token = ""
        while True:
            request = stream_list_pb2.LiveChatMessageListRequest(
                part=["snippet", "authorDetails"],
                live_chat_id=live_chat_id,
                max_results=200,
                page_token=next_page_token,
            )

            try:
                for response in stub.StreamList(request, metadata=metadata):
                    # Filter to only Super Chats and append to SUPERCHATS
                    for msg in response.items:
                        snippet = msg.snippet

                        if snippet.type not in [15, 16, 18]:
                            continue

                        if snippet.type == 15:
                            sc = snippet.super_chat_details
                            message = sc.user_comment
                        elif snippet.type == 16:
                            sc = snippet.super_sticker_details
                            message = "Super Sticker"
                        elif snippet.type == 18:
                            sc = snippet.membership_gifting_details
                            message = f"{sc.gift_memberships_count} Gifted Membership(s)"

                        author = msg.author_details

                        superchat = {
                            "id": msg.id,
                            "author": author.display_name,
                            "authorChannelId": snippet.author_channel_id,
                            "profileImageUrl": author.profile_image_url,
                            "message": message,
                            "amountMicros": sc.amount_micros,
                            "amountDisplayString": sc.amount_display_string,
                            "currency": sc.currency,
                            "tier": sc.tier,
                            "publishedAt": snippet.published_at,
                        }
                        print(f'type: {snippet.type}')
                        print(msg)

                        SUPERCHATS.append(superchat)

                    next_page_token = response.next_page_token or ""
            except grpc.RpcError as e:
                print("gRPC error:", e.code(), e.details())
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    time.sleep(10)
                    continue
                break


async def ensure_superchat_stream_started():
    global SUPERCHAT_THREAD_STARTED, CURRENT_LIVE_CHAT_ID, LIVE_CHAT_CLEAR_TIMER

    with SUPERCHAT_THREAD_LOCK:
        if SUPERCHAT_THREAD_STARTED:
            return

        live_chat_id = await get_live_chat_id(YOUTUBE_CHANNEL_ID)
        if not live_chat_id:
            print("No active YouTube live chat; superchat stream not started.")
            return

        CURRENT_LIVE_CHAT_ID = live_chat_id

        def _clear_live_chat_id(expected_chat_id):
            global CURRENT_LIVE_CHAT_ID, LIVE_CHAT_CLEAR_TIMER
            with SUPERCHAT_THREAD_LOCK:
                if CURRENT_LIVE_CHAT_ID == expected_chat_id:
                    CURRENT_LIVE_CHAT_ID = None
                    print("CURRENT_LIVE_CHAT_ID cleared after 24 hours.")
                LIVE_CHAT_CLEAR_TIMER = None

        if LIVE_CHAT_CLEAR_TIMER is not None:
            LIVE_CHAT_CLEAR_TIMER.cancel()

        LIVE_CHAT_CLEAR_TIMER = threading.Timer(
            datetime.timedelta(hours=24).total_seconds(),
            _clear_live_chat_id,
            args=(live_chat_id,)
        )
        LIVE_CHAT_CLEAR_TIMER.daemon = True
        LIVE_CHAT_CLEAR_TIMER.start()

        def _worker():
            get_superchats(live_chat_id)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        SUPERCHAT_THREAD_STARTED = True
        print("Superchat streaming thread started.")


@app.get("/youtube/streamid")
async def youtube_get_stream_id() -> dict:
    await ensure_superchat_stream_started()

    return {
        "status": 200,
        "liveChatId": CURRENT_LIVE_CHAT_ID,
        "started": SUPERCHAT_THREAD_STARTED,
    }


@app.get("/youtube/superchats")
async def youtube_superchats() -> dict:
    return {
        "status": 200,
        "superchats": list(SUPERCHATS),
    }