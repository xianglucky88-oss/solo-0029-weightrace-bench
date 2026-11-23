from pathlib import Path

from .codec import loads
from .intake import accept_packet
from .sessions import create_session
from .standards import register_standard


def demo_data():
    path = Path(__file__).resolve().parent.parent / "examples" / "linden-shift.json"
    return loads(path.read_bytes())


def load_demo(db):
    data = demo_data()
    key = data["session"]["id"]
    if not db.execute("SELECT 1 FROM sessions WHERE id=?", (key,)).fetchone():
        for item in data["standards"]:
            register_standard(db, item)
        create_session(db, data["session"])
        for packet in data["packets"]:
            accept_packet(db, key, packet)
    return {"id": key}
