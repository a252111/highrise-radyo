import os, asyncio, threading, queue, time, subprocess
import yt_dlp
from flask import Flask, Response
from highrise import BaseBot, User
from highrise.__main__ import main, BotDefinition

BPS = 16000
CHUNK = 4096

listeners = []
llock = threading.Lock()
playlist = []
plock = threading.Lock()
now = {"title": None, "skip": False}


def broadcast(data):
    with llock:
        for q in listeners:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def send_file(path):
    start = time.time()
    sent = 0
    with open(path, "rb") as f:
        while True:
            if now["skip"]:
                break
            chunk = f.read(CHUNK)
            if not chunk:
                break
            broadcast(chunk)
            sent += len(chunk)
            wait = start + sent / BPS - time.time()
            if wait > 0:
                time.sleep(wait)


def radio_loop():
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", "2", "-b:a", "128k", "-ar", "44100", "-ac", "2",
         "-write_xing", "0", "/tmp/silence.mp3"],
        capture_output=True)
    while True:
        with plock:
            item = playlist.pop(0) if playlist else None
        if item:
            path, title = item
            now["title"] = title
            now["skip"] = False
            try:
                send_file(path)
            finally:
                now["title"] = None
                try:
                    os.remove(path)
                except OSError:
                    pass
        else:
            send_file("/tmp/silence.mp3")


def indir(sorgu):
    opts = {
        "format": "bestaudio/best",
        "outtmpl": "/tmp/%(id)s.%(ext)s",
        "default_search": "ytsearch1",
        "noplaylist": True,
        "quiet": True,
        "match_filter": yt_dlp.utils.match_filter_func("duration < 600"),
        "postprocessors": [{"key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "128"}],
        "postprocessor_args": {"ffmpeg": ["-ar", "44100", "-ac", "2"]},
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(sorgu, download=True)
        if "entries" in info:
            info = info["entries"][0] if info["entries"] else None
        if not info:
            raise Exception("bulunamadi")
        path = f"/tmp/{info['id']}.mp3"
        if not os.path.exists(path):
            raise Exception("indirilemedi")
        return path, info["title"]


class Bot(BaseBot):
    async def on_chat(self, user: User, message: str):
        m = message.strip()
        if m.startswith("!play "):
            sorgu = m[6:].strip()
            await self.highrise.chat(f"{sorgu} aranıyor.")
            try:
                path, title = await asyncio.to_thread(indir, sorgu)
            except Exception as e:
                print(e)
                await self.highrise.chat("Şarkı bulunamadı.")
                return
            with plock:
                playlist.append((path, title))
                sira = len(playlist)
            if now["title"] is None and sira == 1:
                await self.highrise.chat(f"{title[:100]} şu an odada çalıyor.")
            else:
                await self.highrise.chat(f"{title[:100]} listeye eklendi. Sıra: {sira}")
        elif m == "!skip":
            now["skip"] = True
            await self.highrise.chat("Şarkı geçildi.")
        elif m == "!liste":
            with plock:
                t = [x[1][:40] for x in playlist]
            cal = now["title"] or "Yok"
            await self.highrise.chat(f"Çalan: {cal[:60]} | Sırada: {', '.join(t) if t else 'Boş'}")


app = Flask(__name__)


@app.route("/")
def ok():
    return "ok"


@app.route("/stream")
def stream():
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
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=radio_loop, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True),
        daemon=True).start()
    asyncio.run(main([BotDefinition(Bot(), os.environ["ROOM_ID"], os.environ["BOT_TOKEN"])]))
