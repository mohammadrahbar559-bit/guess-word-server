import random
import string
import time
import uuid

from word_bank import WORDS, draw_word
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Guess Word API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

rooms = {}


class Create(BaseModel):
    name: str = Field(default="Player", max_length=18)
    mode: str = "random"
    custom_word: str = ""


class Join(BaseModel):
    name: str = Field(default="Player", max_length=18)


class Guess(BaseModel):
    player_id: str
    letter: str


class NextRound(BaseModel):
    player_id: str
    round_id: int


def code_new():
    for _ in range(100):
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if code not in rooms:
            return code
    raise HTTPException(500, "Could not create room")


def player(name):
    return {
        "id": uuid.uuid4().hex,
        "name": (name.strip() or "Player")[:18],
        "guesses": 0,
        "solved": False,
        "solved_at": None,
    }


def create(name, mode="random", custom=""):
    if mode not in ("random", "challenge"):
        raise HTTPException(400, "Invalid mode")

    if mode == "challenge":
        word = custom.strip().upper()
        if not (2 <= len(word) <= 12 and word.isalpha()):
            raise HTTPException(
                400, "Challenge word must be 2-12 English letters"
            )
        hint = "A word chosen by the room creator"
    else:
        word, hint = draw_word()

    code = code_new()
    first_player = player(name)

    room = {
        "code": code,
        "word": word,
        "hint": hint,
        "mode": mode,
        "players": [first_player],
        "guessed": set(),
        "turn_index": 0,
        "round_id": 1,
        "over": False,
        "winner": None,
        "message": "Waiting for opponent to join.",
    }

    rooms[code] = room
    return room, first_player


def getroom(code):
    if code.upper() not in rooms:
        raise HTTPException(404, "Room not found. Check the code.")
    return rooms[code.upper()]


def getplayer(room, player_id):
    for p in room["players"]:
        if p["id"] == player_id:
            return p
    raise HTTPException(403, "Player not in this room")


def state(room, player_id):
    me = getplayer(room, player_id)
    ready = len(room["players"]) == 2

    current = (
        room["players"][room["turn_index"]]
        if ready and not room["over"]
        else None
    )

    winner = next(
        (p["name"] for p in room["players"] if p["id"] == room["winner"]),
        None,
    )

    return {
        "room_code": room["code"],
        "mode": room["mode"],
        "hint": room["hint"],
        "word_mask": "".join(
            letter if letter in room["guessed"] else "_"
            for letter in room["word"]
        ),
        "players": [
            {
                "name": p["name"],
                "guesses": p["guesses"],
                "solved": p["solved"],
            }
            for p in room["players"]
        ],
        "my_guessed": sorted(room["guessed"]),
        "my_solved": me["solved"],
        "ready": ready,
        "round_over": room["over"],
        "winner_name": winner,
        "message": room["message"],
        "round_id": room["round_id"],
        "my_turn": bool(current and current["id"] == player_id),
        "turn_player_name": current["name"] if current else None,
        "next_word_available": room["over"],
    }


@app.get("/")
def root():
    return {"name": "Guess Word API", "status": "ok", "rooms": len(rooms)}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/rooms")
def make_room(req: Create):
    room, p = create(req.name, req.mode, req.custom_word)
    return {
        "room_code": room["code"],
        "player_id": p["id"],
        "mode": room["mode"],
    }


@app.post("/rooms/{code}/join")
def join(code: str, req: Join):
    room = getroom(code)

    if room["over"] or len(room["players"]) >= 2:
        raise HTTPException(409, "Room is full or match has ended")

    p = player(req.name)
    room["players"].append(p)
    room["message"] = (
        "Both players joined. " + room["players"][0]["name"] + " starts!"
    )

    return {
        "room_code": room["code"],
        "player_id": p["id"],
        "mode": room["mode"],
    }


@app.post("/rooms/{code}/guess")
def guess(code: str, req: Guess):
    room = getroom(code)
    p = getplayer(room, req.player_id)
    letter = req.letter.strip().upper()

    if len(letter) != 1 or letter not in string.ascii_uppercase:
        raise HTTPException(400, "Enter one letter A-Z")

    if len(room["players"]) < 2:
        raise HTTPException(409, "Waiting for the second player to join")

    if room["over"]:
        raise HTTPException(409, "Round is over")

    current = room["players"][room["turn_index"]]
    if current["id"] != p["id"]:
        raise HTTPException(409, "Not your turn. Wait for your opponent.")

    if letter in room["guessed"]:
        raise HTTPException(409, "Letter already guessed")

    room["guessed"].add(letter)
    p["guesses"] += 1

    if all(char in room["guessed"] for char in set(room["word"])):
        p["solved"] = True
        p["solved_at"] = time.time()
        room["over"] = True
        room["winner"] = p["id"]
        room["message"] = p["name"] + " wins! Word completed!"
    else:
        next_index = 1 - room["turn_index"]
        next_player = room["players"][next_index]
        room["turn_index"] = next_index

        if letter in room["word"]:
            result = "Correct letter!"
        else:
            result = "Wrong guess. No penalty."

        room["message"] = (
            p["name"] + ": " + result
            + " Next turn: " + next_player["name"] + "."
        )

    return state(room, req.player_id)


@app.post("/rooms/{code}/next")
def next_round(code: str, req: NextRound):
    room = getroom(code)
    getplayer(room, req.player_id)

    # Stale requests from an older round must not skip the new word.
    if req.round_id != room["round_id"]:
        return state(room, req.player_id)

    if not room["over"]:
        raise HTTPException(409, "Current round is not over yet")

    if room["mode"] == "random":
        word, hint = draw_word()
    else:
        word, hint = room["word"], room["hint"]

    room["word"] = word
    room["hint"] = hint
    room["guessed"] = set()
    room["turn_index"] = 0
    room["round_id"] += 1
    room["over"] = False
    room["winner"] = None

    for p in room["players"]:
        p["guesses"] = 0
        p["solved"] = False
        p["solved_at"] = None

    room["message"] = (
        "New round! " + room["players"][0]["name"] + " starts."
    )

    return state(room, req.player_id)


@app.get("/rooms/{code}/state")
def room_state(code: str, player_id: str):
    return state(getroom(code), player_id)
