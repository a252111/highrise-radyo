import os, re, asyncio, threading, queue, time, subprocess, json, random
import urllib.request
import yt_dlp
from flask import Flask, Response, request
from highrise import BaseBot, User, Position
from highrise.__main__ import main, BotDefinition

# ================= AYARLAR =================
OWNER = os.environ.get("OWNER_NAME", "RQTM").lower()      # bot sahibi
DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "ar")        # ar / tr / en
BOT_POS = Position(11.0, 7.0, 11.0)                        # bot konumu
HINT_EVERY = 60                                            # saniye
MAX_SEC = 720                                              # en uzun sarki (sn)
MIN_SEC = 60                                               # 30 sn onizlemeleri atla
DATA_FILE = os.environ.get("DATA_FILE", "/tmp/data.json")
UPSTASH_URL = os.environ.get("UPSTASH_URL")                # opsiyonel kalici depo
UPSTASH_TOKEN = os.environ.get("UPSTASH_TOKEN")

# Renkler (sohbette <#RRGGBB> etiketi)
BLUE, WHITE, GREEN, RED, YELLOW = "3399FF", "FFFFFF", "00FF66", "FF3333", "FFD700"


def col(hexc, text):
    return f"<#{hexc}>{text}"


# Dans listesi (calismayan olursa sessizce atlanir)
EMOTES = [
    "dance-macarena", "dance-tiktok8", "dance-tiktok9", "dance-tiktok10",
    "dance-tiktok2", "dance-blackpink", "dance-pennywise", "dance-shoppingcart",
    "dance-russian", "dance-weird", "dance-employee", "dance-breakdance",
    "emote-gordonshuffle", "dance-icecream", "dance-wrong", "dance-touch",
    "idle-dance-casual",
]

# ================= METINLER =================
L = {
    "ar": {
        "search": "جار البحث عن أغنية",
        "added": "تمت إضافته إلى القائمة، يمكنك الاستماع بعد {n} أغنية 🎶",
        "wait": "عليك الانتظار حتى تنتهي الأغنية السابقة قبل أن تتمكن من بدء أغنية أخرى 🛑",
        "notfound": "الأغنية التي طلبتها غير متوفرة",
        "playing_a": "الأغنية التالية قيد التشغيل 🎶",
        "playing_b": "، مالك الأغنية",
        "hint": "لتشغيل الأغنية التي تريدها، اكتب !play و اسم الأغنية. 🎵🎼",
        "owner_added": "تمت إضافة {u} كمالك للبوت ✅",
        "no_perm": "ليس لديك صلاحية ⛔",
        "paused": "تم إيقاف الأغنية ⏸",
        "resumed": "تم استئناف الأغنية ▶️",
        "deleted": "تم حذف الأغنية الحالية 🗑",
        "restarted": "تمت إعادة الأغنية 🔁",
        "lang_set": "تم تعيين اللغة: العربية ✅",
        "empty": "لا توجد أغنية",
        "now": "يعمل الآن",
        "next": "التالي",
        "nothing": "فارغ",
    },
    "tr": {
        "search": "Şarkı aranıyor:",
        "added": "listeye eklendi, {n} şarkı sonra dinleyebilirsin 🎶",
        "wait": "Yeni şarkı açmak için önceki şarkının bitmesini beklemelisin 🛑",
        "notfound": "İstediğin şarkı bulunamadı",
        "playing_a": "Sıradaki şarkı çalıyor 🎶",
        "playing_b": ", şarkı sahibi:",
        "hint": "İstediğin şarkıyı çalmak için !play yazıp şarkı adını yaz. 🎵🎼",
        "owner_added": "{u} bot sahibi yapıldı ✅",
        "no_perm": "Yetkin yok ⛔",
        "paused": "Şarkı durduruldu ⏸",
        "resumed": "Şarkı devam ediyor ▶️",
        "deleted": "Çalan şarkı silindi 🗑",
        "restarted": "Şarkı baştan başlatıldı 🔁",
        "lang_set": "Dil Türkçe olarak ayarlandı ✅",
        "empty": "Çalan şarkı yok",
        "now": "Çalan",
        "next": "Sırada",
        "nothing": "Boş",
    },
    "en": {
        "search": "Searching for song:",
        "added": "added to the list, you can listen after {n} songs 🎶",
        "wait": "You must wait for your previous song to finish before starting another 🛑",
        "notfound": "The song you requested is not available",
        "playing_a": "Next song is now playing 🎶",
        "playing_b": ", song owner:",
        "hint": "To play a song you want, type !play and the song name. 🎵🎼",
        "owner_added": "{u} is now a bot owner ✅",
        "no_perm": "You don't have permission ⛔",
        "paused": "Song paused ⏸",
        "resumed": "Song resumed ▶️",
        "deleted": "Current song deleted 🗑",
        "restarted": "Song restarted 🔁",
        "lang_set": "Language set to English ✅",
        "empty": "No song playing",
        "now": "Now",
        "next": "Next",
        "nothing": "Empty",
    },
}

# ================= KALICI VERI =================
data = {"lang": DEFAULT_LANG if DEFAULT_LANG in L else "ar", "owners": []}
dlock = threading.Lock()


def _up(path, body=None):
    req = urllib.request.Request(
        UPSTASH_URL.rstrip("/") + path,
        data=body.encode() if body is not None else None,
        headers={"Authorization": "Bearer " + UPSTASH_TOKEN},
        method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def load_data():
    try:
        if UPSTASH_URL and UPSTASH_TOKEN:
            res = _up("/get/radio_data").get("result")
            if res:
                data.update(json.loads(res))
        elif os.path.exists(DATA_FILE):
            data.update(json.load(open(DATA_FILE)))
    except Exception as e:
        print("HATA veri yukle", e, flush=True)


def save_data():
    try:
        with dlock:
            s = json.dumps(data)
        if UPSTASH_URL and UPSTASH_TOKEN:
            _up("/set/radio_data", s)
        else:
            open(DATA_FILE, "w").write(s)
    except Exception as e:
        print("HATA veri kaydet", e, flush=True)


def T():
    return L[data["lang"]]


def is_owner(name):
    n = (name or "").lower().lstrip("@")
    return n == OWNER or n in data["owners"]


# ================= RADYO =================
BPS = 16000
CHUNK = 4096
listeners = []
llock = threading.Lock()
playlist = []          # (path, title, user_id, username)
plock = threading.Lock()
state = {"title": None, "user_id": None, "username": None,
         "skip": False, "restart": False, "paused": False}
BOT = {"inst": None, "loop": None}


def say(msg):
    b, lp = BOT["inst"], BOT["loop"]
    if b and lp:
        asyncio.run_coroutine_threadsafe(b.highrise.chat(msg[:255]), lp)


def broadcast(buf):
    with llock:
        for q in listeners:
            try:
                q.put_nowait(buf)
            except queue.Full:
                pass


def playing_msg(title, uname):
    t = T()
    return (col(GREEN, t["playing_a"]) + " " + col(WHITE, title[:60]) +
            col(GREEN, t["playing_b"]) + " " + col(BLUE, uname))


def radio_loop():
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", "4", "-b:a", "128k", "-ar", "44100", "-ac", "2",
         "-write_xing", "0", "/tmp/silence.mp3"], capture_output=True)
    SIL = open("/tmp/silence.mp3", "rb").read()
    si = 0
    next_t = time.time()

    def pace(n):
        nonlocal next_t
        next_t += n / BPS
        d = next_t - time.time()
        if d > 0:
            time.sleep(d)
        elif d < -1:
            next_t = time.time()

    def sil_chunk():
        nonlocal si
        c = SIL[si:si + CHUNK]
        si = (si + CHUNK) % (len(SIL) - CHUNK)
        return c

    while True:
        with plock:
            item = playlist.pop(0) if playlist else None
        if not item:
            c = sil_chunk()
            broadcast(c)
            pace(len(c))
            continue
        path, title, uid, uname = item
        state.update(title=title, user_id=uid, username=uname,
                     skip=False, restart=False, paused=False)
        say(playing_msg(title, uname))
        try:
            buf = open(path, "rb").read()
            pos = 0
            next_t = time.time()
            while pos < len(buf):
                if state["skip"]:
                    break
                if state["restart"]:
                    pos = 0
                    state["restart"] = False
                if state["paused"]:
                    c = sil_chunk()
                else:
                    c = buf[pos:pos + CHUNK]
                    pos += CHUNK
                broadcast(c)
                pace(len(c))
        except Exception as e:
            print("HATA calma", e, flush=True)
        finally:
            state.update(title=None, user_id=None, username=None,
                         skip=False, paused=False)
            try:
                os.remove(path)
            except OSError:
                pass


# ================= SARKI BULMA =================
TR_MAP = str.maketrans("İıŞşĞğÜüÖöÇç", "IiSsGgUuOoCc")
BAD_WORDS = ("remix", "live", "cover", "karaoke", "slowed", "reverb",
             "sped up", "nightcore", "8d", "instrumental", "full album",
             "playlist", "1 hour", "mix")
YT_API_KEY = os.environ.get("YT_API_KEY")        # opsiyonel (sadece arama)
YT_COOKIES = os.environ.get("YT_COOKIES")        # opsiyonel (cookies.txt icerigi)
YT = {"blocked_at": 0.0}
COOKIE_FILE = None
if YT_COOKIES:
    try:
        open("/tmp/cookies.txt", "w").write(YT_COOKIES)
        COOKIE_FILE = "/tmp/cookies.txt"
    except Exception as _e:
        print("HATA cookie", _e, flush=True)


def norm(x):
    x = (x or "").translate(TR_MAP).lower()
    return re.sub(r"[^a-z0-9\u0600-\u06ff ]", " ", x)


def score(e, qnorm, qwords):
    title = norm((e.get("title") or "") + " " +
                 (e.get("uploader") or e.get("channel") or ""))
    dur = e.get("duration")
    if dur and (dur > MAX_SEC or dur < MIN_SEC):
        return None
    hit = sum(1 for w in qwords if w in title)
    if qwords and hit == 0:
        return None
    sc = 10.0 * hit / max(1, len(qwords))
    for w in BAD_WORDS:
        if w in title and w not in qnorm:
            sc -= 3
    if dur and 120 <= dur <= 480:
        sc += 1
    if "official" in title or "topic" in title:
        sc += 0.5
    return sc


def _search(prefix, q):
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                           "extract_flat": True, "socket_timeout": 15,
                           "cookiefile": COOKIE_FILE}) as y:
        res = y.extract_info(f"{prefix}:{q}", download=False)
    out = []
    for e in (res.get("entries") or []):
        if e:
            e = dict(e)
            e["_url"] = e.get("webpage_url") or e.get("url")
            out.append(e)
    return out


def _yt_api(q):
    import urllib.parse
    u = ("https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
         "&maxResults=8&q=" + urllib.parse.quote(q) + "&key=" + YT_API_KEY)
    with urllib.request.urlopen(u, timeout=10) as r:
        js = json.loads(r.read().decode())
    return [{"title": i["snippet"]["title"],
             "uploader": i["snippet"]["channelTitle"],
             "duration": None,
             "_url": "https://www.youtube.com/watch?v=" + i["id"]["videoId"]}
            for i in js.get("items", []) if i.get("id", {}).get("videoId")]


def _dailymotion(q):
    import urllib.parse
    u = ("https://api.dailymotion.com/videos?fields=id,title,duration,owner.screenname"
         "&limit=10&search=" + urllib.parse.quote(q))
    with urllib.request.urlopen(u, timeout=12) as r:
        js = json.loads(r.read().decode())
    return [{"title": i.get("title"), "uploader": i.get("owner.screenname"),
             "duration": i.get("duration"),
             "_url": "https://www.dailymotion.com/video/" + i["id"], "_src": "dm"}
            for i in js.get("list", []) if i.get("id")]


def _audius(q):
    import urllib.parse
    u = ("https://api.audius.co/v1/tracks/search?app_name=highriseradyo&query="
         + urllib.parse.quote(q))
    with urllib.request.urlopen(u, timeout=12) as r:
        js = json.loads(r.read().decode())
    return [{"title": i.get("title"), "uploader": (i.get("user") or {}).get("name"),
             "duration": i.get("duration"),
             "_url": "https://api.audius.co/v1/tracks/%s/stream?app_name=highriseradyo" % i["id"],
             "_src": "au"}
            for i in js.get("data", []) if i.get("id")]


def _download_audius(url, title):
    raw = "/tmp/au_%d.raw" % int(time.time() * 1000)
    out = raw + ".mp3"
    with urllib.request.urlopen(url, timeout=30) as r, open(raw, "wb") as f:
        while True:
            b = r.read(65536)
            if not b:
                break
            f.write(b)
    p = subprocess.run(["ffmpeg", "-y", "-i", raw, "-vn", "-b:a", "128k",
                        "-ar", "44100", "-ac", "2", out], capture_output=True)
    try:
        os.remove(raw)
    except OSError:
        pass
    if p.returncode != 0 or not os.path.exists(out):
        raise Exception("audius donusturulemedi")
    return out, title or "Song"


def _download(url):
    opts = {
        "format": "bestaudio[abr<=160]/bestaudio/best",
        "outtmpl": "/tmp/%(id)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 2,
        "concurrent_fragment_downloads": 4,
        "cookiefile": COOKIE_FILE,
        "postprocessors": [{"key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "128"}],
        "postprocessor_args": {"ffmpeg": ["-ar", "44100", "-ac", "2"]},
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        if "entries" in info:
            info = info["entries"][0]
        path = os.path.splitext(y.prepare_filename(info))[0] + ".mp3"
    if not os.path.exists(path):
        raise Exception("dosya olusmadi")
    return path, info.get("title") or "Song"


def indir(sorgu):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    q0 = sorgu.strip()
    ascii_q = q0.translate(TR_MAP)
    variants = [q0]
    variants.append(ascii_q if ascii_q != q0 else q0 + " official audio")
    variants.append(q0 + " lyrics")
    qnorm = norm(q0)
    qwords = [w for w in qnorm.split() if len(w) > 1]

    jobs = [(p, q) for q in variants for p in ("scsearch12", "ytsearch8")]
    cands = {}
    last = None
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_search, p, q) for p, q in jobs]
        for qq in variants[:2]:
            futs.append(ex.submit(_dailymotion, qq))
            futs.append(ex.submit(_audius, qq))
        if YT_API_KEY:
            futs.append(ex.submit(_yt_api, q0))
        try:
            for f in as_completed(futs, timeout=45):
                try:
                    for e in f.result():
                        if e.get("_url") and e["_url"] not in cands:
                            cands[e["_url"]] = e
                except Exception as e:
                    print("HATA arama", e, flush=True)
                    last = e
        except Exception as e:
            print("HATA arama zaman asimi", e, flush=True)

    ranked = []
    for e in cands.values():
        sc = score(e, qnorm, qwords)
        if sc is not None:
            ranked.append((sc, e))
    ranked.sort(key=lambda x: -x[0])
    order = [e for _, e in ranked] or list(cands.values())
    print("ADAY", len(cands), "SECILEN", len(order), flush=True)

    def is_yt(e):
        return "youtube.com" in e["_url"] or "youtu.be" in e["_url"]

    blocked = time.time() - YT["blocked_at"] < 600
    non_yt = [e for e in order if not is_yt(e)][:8]
    yt_list = [e for e in order if is_yt(e)][:2]
    allow = set(id(e) for e in non_yt)
    if not blocked:
        allow |= set(id(e) for e in yt_list)
    tries = [e for e in order if id(e) in allow]
    print("DENENECEK", len(tries), "YT_ENGEL", blocked, flush=True)
    for e in tries:
        if is_yt(e) and time.time() - YT["blocked_at"] < 600:
            continue
        try:
            if e.get("_src") == "au":
                return _download_audius(e["_url"], e.get("title"))
            return _download(e["_url"])
        except Exception as ex:
            msg = str(ex)
            print("HATA indir", e.get("_src") or "x", e["_url"][:80], msg[:150], flush=True)
            last = ex
            if "not a bot" in msg or "Sign in" in msg:
                YT["blocked_at"] = time.time()
    raise last or Exception("bulunamadi")


# ================= BOT =================
class Bot(BaseBot):
    def __init__(self):
        super().__init__()
        self.id2name = {}
        self.pending = set()

    async def on_start(self, session_metadata):
        BOT["inst"] = self
        BOT["loop"] = asyncio.get_running_loop()
        self.my_id = session_metadata.user_id
        await self.refresh_users()
        try:
            await self.highrise.teleport(self.my_id, BOT_POS)
        except Exception as e:
            print("HATA teleport", e, flush=True)
        asyncio.create_task(self.dance_loop())
        asyncio.create_task(self.hint_loop())

    async def refresh_users(self):
        try:
            room = await self.highrise.get_room_users()
            for u, _ in room.content:
                self.id2name[u.id] = u.username
        except Exception as e:
            print("HATA oda", e, flush=True)

    async def on_user_join(self, user: User, position=None):
        self.id2name[user.id] = user.username

    async def dance_loop(self):
        while True:
            for em in random.sample(EMOTES, len(EMOTES)):
                try:
                    await self.highrise.send_emote(em)
                except Exception:
                    pass
                await asyncio.sleep(random.randint(8, 12))

    async def hint_loop(self):
        while True:
            await asyncio.sleep(HINT_EVERY)
            try:
                await self.highrise.chat(col(GREEN, T()["hint"]))
            except Exception as e:
                print("HATA ipucu", e, flush=True)

    def user_has_song(self, uid):
        if state["user_id"] == uid:
            return True
        with plock:
            return any(x[2] == uid for x in playlist)

    async def on_chat(self, user: User, message: str):
        self.id2name[user.id] = user.username
        m = message.strip()
        t = T()
        owner = is_owner(user.username)

        if m.lower().startswith("!play "):
            sorgu = m[6:].strip()
            if not sorgu:
                return
            if not owner and (user.id in self.pending or self.user_has_song(user.id)):
                await self.highrise.chat(col(RED, t["wait"]))
                return
            self.pending.add(user.id)
            try:
                await self.highrise.chat(
                    t["search"] + " " + col(BLUE, sorgu[:60]) + " | " +
                    col(WHITE, user.username) + " " +
                    col(GREEN, "▰▰") + col(RED, "▱▱▱"))
                try:
                    path, title = await asyncio.to_thread(indir, sorgu)
                except Exception as e:
                    print("HATA genel", e, flush=True)
                    await self.highrise.chat(
                        col(RED, t["notfound"]) + " " + col(BLUE, user.username) + " ⚠️")
                    return
                with plock:
                    playlist.append((path, title, user.id, user.username))
                    ahead = len(playlist) - 1 + (1 if state["title"] else 0)
                if ahead > 0:
                    await self.highrise.chat(
                        col(WHITE, title[:60]) + " " +
                        col(YELLOW, t["added"].format(n=ahead)))
            finally:
                self.pending.discard(user.id)

        elif m.startswith("!ضيف_مالك"):
            if user.username.lower() != OWNER:
                await self.highrise.chat(t["no_perm"])
                return
            parts = m.split()
            if len(parts) < 2:
                return
            name = parts[1].lstrip("@").lower()
            if name not in data["owners"]:
                data["owners"].append(name)
                await asyncio.to_thread(save_data)
            await self.highrise.chat(t["owner_added"].format(u="@" + name))

        elif m in ("!وقف", "!تشغيل", "!مسح", "!اعادة", "!إعادة", "!skip"):
            if not owner:
                await self.highrise.chat(t["no_perm"])
                return
            if m == "!وقف":
                state["paused"] = True
                await self.highrise.chat(t["paused"])
            elif m == "!تشغيل":
                state["paused"] = False
                await self.highrise.chat(t["resumed"])
            elif m in ("!مسح", "!skip"):
                state["skip"] = True
                await self.highrise.chat(t["deleted"])
            else:
                state["restart"] = True
                state["paused"] = False
                await self.highrise.chat(t["restarted"])

        elif m in ("!liste", "!list", "!قائمة"):
            with plock:
                nxt = [x[1][:30] for x in playlist]
            cur = state["title"] or t["empty"]
            await self.highrise.chat(
                f"{t['now']}: {cur[:50]} | {t['next']}: "
                f"{', '.join(nxt) if nxt else t['nothing']}")

    async def on_message(self, user_id: str, conversation_id: str,
                         is_new_conversation: bool):
        try:
            resp = await self.highrise.get_messages(conversation_id)
            msgs = getattr(resp, "messages", None)
            if not msgs:
                return
            text = (msgs[0].content or "").strip().lower()
            if text not in ("ar", "tr", "en"):
                return
            if user_id not in self.id2name:
                await self.refresh_users()
            if not is_owner(self.id2name.get(user_id)):
                return
            data["lang"] = text
            await asyncio.to_thread(save_data)
            await self.highrise.send_message(conversation_id, L[text]["lang_set"])
        except Exception as e:
            print("HATA dm", e, flush=True)


# ================= WEB (RADYO YAYINI) =================
app = Flask(__name__)


@app.route("/")
def ok():
    return "ok"


@app.route("/radio.mp3", methods=["GET", "HEAD"])
@app.route("/stream", methods=["GET", "HEAD"])
def stream():
    if request.method == "HEAD":
        return Response(b"", mimetype="audio/mpeg", headers={"icy-name": "Radyo"})
    q = queue.Queue(maxsize=300)
    with llock:
        listeners.append(q)

    def gen():
        try:
            while True:
                yield q.get()
        finally:
            with llock:
                if q in listeners:
                    listeners.remove(q)

    return Response(gen(), mimetype="audio/mpeg",
                    headers={"Cache-Control": "no-cache", "icy-name": "Radyo"})


if __name__ == "__main__":
    load_data()
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=radio_loop, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True),
        daemon=True).start()
    asyncio.run(main([BotDefinition(Bot(), os.environ["ROOM_ID"], os.environ["BOT_TOKEN"])]))
