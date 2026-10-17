import random, string, time, uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
app=FastAPI(title="Guess Word API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
WORDS=[("APPLE","A fruit that can be red or green"),("HOUSE","A place where people live"),("PLANT","A living thing that grows in soil"),("CHAIR","Something you sit on"),("BREAD","A common food made from flour"),("WATER","You drink this every day"),("TIGER","A large striped wild cat"),("GRAPE","A small fruit that grows in bunches"),("CLOUD","A white or grey shape in the sky"),("SMILE","A happy expression"),("ROCKET","A vehicle that can travel into space"),("PYTHON","A popular programming language"),("GUITAR","A musical instrument with strings"),("PLANET","Earth is one of these"),("RAINBOW","A colourful arc seen after rain"),("JOURNEY","A trip from one place to another"),("KEYBOARD","You can type on this"),("ELEPHANT","A very large animal with a trunk"),("NOTEBOOK","A book used for writing notes"),("ADVENTURE","An exciting or unusual experience")]
rooms={}
class Create(BaseModel):
    name:str=Field(default="Player",max_length=18); mode:str="random"; custom_word:str=""
class Join(BaseModel): name:str=Field(default="Player",max_length=18)
class Guess(BaseModel): player_id:str; letter:str
def code_new():
    for _ in range(100):
        c="".join(random.choices(string.ascii_uppercase+string.digits,k=5))
        if c not in rooms:return c
    raise HTTPException(500,"Could not create room")
def player(name): return {"id":uuid.uuid4().hex,"name":(name.strip() or "Player")[:18],"guessed":set(),"guesses":0,"solved":False,"solved_at":None}
def create(name,mode="random",custom=""):
    if mode not in ("random","challenge"):raise HTTPException(400,"Invalid mode")
    if mode=="challenge":
        word=custom.strip().upper()
        if not (2<=len(word)<=12 and word.isalpha()):raise HTTPException(400,"Challenge word must be 2–12 letters")
        hint="A word chosen by the room creator"
    else:word,hint=random.choice(WORDS)
    c=code_new(); p=player(name); room={"code":c,"word":word,"hint":hint,"mode":mode,"players":[p],"over":False,"winner":None,"message":"Waiting for opponent to join."}; rooms[c]=room
    return room,p
def getroom(c):
    if c.upper() not in rooms:raise HTTPException(404,"Room not found. Check the code.")
    return rooms[c.upper()]
def getplayer(r,pid):
    for p in r["players"]:
        if p["id"]==pid:return p
    raise HTTPException(403,"Player not in this room")
def state(r,pid):
    me=getplayer(r,pid); ps=[{"name":p["name"],"guesses":p["guesses"],"solved":p["solved"]} for p in r["players"]]
    winner=next((p["name"] for p in r["players"] if p["id"]==r["winner"]),None)
    ready=len(r["players"])==2
    return {"room_code":r["code"],"mode":r["mode"],"hint":r["hint"],"word_mask":" ".join(c if c in me["guessed"] else "_" for c in r["word"]),"players":ps,"my_guessed":sorted(me["guessed"]),"my_solved":me["solved"],"ready":ready,"round_over":r["over"],"winner_name":winner,"message":r["message"]}

@app.get("/")
def root():return {"name":"Guess Word API","status":"ok","rooms":len(rooms)}
@app.get("/health")
def health():return {"ok":True}
@app.post("/rooms")
def make_room(req:Create):
    r,p=create(req.name,req.mode,req.custom_word); return {"room_code":r["code"],"player_id":p["id"],"mode":r["mode"]}
@app.post("/rooms/{c}/join")
def join(c:str,req:Join):
    r=getroom(c)
    if len(r["players"])>=2:raise HTTPException(409,"Room is full")
    p=player(req.name);r["players"].append(p);r["message"]="Both players joined. Same word for both — start guessing!"
    return {"room_code":r["code"],"player_id":p["id"],"mode":r["mode"]}
@app.post("/rooms/{c}/guess")
def guess(c:str,req:Guess):
    r=getroom(c);p=getplayer(r,req.player_id);letter=req.letter.strip().upper()
    if len(letter)!=1 or letter not in string.ascii_uppercase:raise HTTPException(400,"Enter one letter A–Z")
    if len(r["players"])<2:raise HTTPException(409,"Waiting for the second player to join")
    if r["over"]:raise HTTPException(409,"Round is over")
    if p["solved"]:raise HTTPException(409,"You already solved this word")
    if letter in p["guessed"]:raise HTTPException(409,"Letter already guessed")
    p["guessed"].add(letter);p["guesses"]+=1
    if all(c in p["guessed"] for c in set(r["word"])):
        p["solved"]=True;p["solved_at"]=time.time();r["message"]=p["name"]+" solved the word!"
    elif letter in r["word"]:r["message"]=p["name"]+" guessed a correct letter."
    else:r["message"]="Wrong guess. No penalty!"
    if len(r["players"])==2 and all(x["solved"] for x in r["players"]):
        r["over"]=True;a,b=r["players"]
        if a["guesses"]<b["guesses"]:r["winner"]=a["id"]
        elif b["guesses"]<a["guesses"]:r["winner"]=b["id"]
        else:r["winner"]=min((a,b),key=lambda x:x["solved_at"])["id"]
        r["message"]="Round complete!"
    return state(r,req.player_id)
@app.get("/rooms/{c}/state")
def room_state(c:str,player_id:str):return state(getroom(c),player_id)
