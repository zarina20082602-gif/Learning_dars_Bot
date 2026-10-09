import asyncio,json,os,random,time
from pathlib import Path
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command
from aiogram.types import Message,CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

BASE=Path(__file__).parent
DATA=json.load(open(BASE/"questions.json",encoding="utf-8"))["subjects"]
dp=Dispatcher(); sessions={}

def subjects_menu():
    kb=InlineKeyboardBuilder()
    for key,s in DATA.items(): kb.button(text=s["title"],callback_data=f"sub:{key}")
    kb.adjust(1); return kb.as_markup()

def modes(key):
    kb=InlineKeyboardBuilder()
    kb.button(text="🧠 Yodlash",callback_data=f"mode:learn:{key}")
    kb.button(text="🔀 Mashq",callback_data=f"mode:train:{key}")
    kb.button(text="📝 Imtihon",callback_data=f"mode:exam:{key}")
    kb.button(text="⬅️ Fanlar",callback_data="subjects")
    kb.adjust(1); return kb.as_markup()

def answer_kb(sess,q,learn=False):
    kb=InlineKeyboardBuilder()
    if learn:
        kb.button(text="➡️ Keyingi",callback_data=f"next:{sess['nonce']}")
    else:
        for i,_ in enumerate(q["options"]):
            kb.button(text=chr(65+i),callback_data=f"ans:{sess['nonce']}:{i}")
        kb.adjust(2)
    return kb.as_markup()

def textq(q,num=None,total=None,show=False):
    head=f"{num}/{total}\n\n" if num else ""
    body=head+q["question"]+"\n\n"+"\n".join(f"{chr(65+i)}) {x}" for i,x in enumerate(q["options"]))
    if show and not q.get("verified",True):
        body+="\n\n⚠️ Javob manbada tasdiqlanmagan"
    if show and q.get("verified",True):
        body+="\n\n✅ To‘g‘ri javob: "+", ".join(chr(65+i) for i in q["correct"])
    return body

async def send_current(target,uid):
    s=sessions.get(uid)
    if not s: return
    if s["pos"]>=len(s["ids"]):
        if s["mode"]=="exam":
            await target.answer(f"📝 Imtihon yakunlandi\n\nNatija: {s['score']}/{len(s['ids'])}")
        elif s["mode"]=="train":
            await target.answer(f"🔀 Mashq yakunlandi\n\nNatija: {s['score']}/{len(s['ids'])}")
        else: await target.answer("✅ Yodlash yakunlandi")
        sessions.pop(uid,None); return
    q=DATA[s["subject"]]["questions"][s["ids"][s["pos"]]]
    s["nonce"]=str(time.time_ns())
    await target.answer(textq(q,s["pos"]+1,len(s["ids"]),s["mode"]=="learn"),
                        reply_markup=answer_kb(s,q,s["mode"]=="learn"))

@dp.message(Command("start"))
async def start(m:Message):
    sessions.pop(m.from_user.id,None)
    await m.answer("📚 Fanni tanlang:",reply_markup=subjects_menu())

@dp.callback_query(F.data=="subjects")
async def subback(c:CallbackQuery):
    sessions.pop(c.from_user.id,None); await c.answer()
    await c.message.answer("📚 Fanni tanlang:",reply_markup=subjects_menu())

@dp.callback_query(F.data.startswith("sub:"))
async def subject(c:CallbackQuery):
    await c.answer(); key=c.data.split(":",1)[1]
    await c.message.answer(f"{DATA[key]['title']}\n\nBazadagi savollar: {len(DATA[key]['questions'])} ta\nRejimni tanlang:",reply_markup=modes(key))

@dp.callback_query(F.data.startswith("mode:"))
async def mode(c:CallbackQuery):
    await c.answer(); _,md,key=c.data.split(":")
    n=len(DATA[key]["questions"])
    ids=list(range(n))
    if md in ("exam","train"):
        ids=[i for i,q in enumerate(DATA[key]["questions"]) if q.get("verified",True) and q.get("correct") and len(q.get("options",[]))>=3]
        random.shuffle(ids)
        if md=="exam": ids=ids[:min(50,len(ids))]
    sessions[c.from_user.id]={"subject":key,"mode":md,"ids":ids,"pos":0,"score":0,"nonce":None}
    await send_current(c.message,c.from_user.id)

@dp.callback_query(F.data.startswith("next:"))
async def nxt(c:CallbackQuery):
    s=sessions.get(c.from_user.id)
    if not s or c.data.split(":")[1]!=s.get("nonce"): return await c.answer()
    await c.answer(); s["nonce"]=None
    try: await c.message.edit_reply_markup(reply_markup=None)
    except: pass
    s["pos"]+=1; await send_current(c.message,c.from_user.id)

@dp.callback_query(F.data.startswith("ans:"))
async def ans(c:CallbackQuery):
    s=sessions.get(c.from_user.id)
    if not s: return await c.answer()
    _,nonce,raw=c.data.split(":")
    if nonce!=s.get("nonce"): return await c.answer()
    s["nonce"]=None; choice=int(raw)
    q=DATA[s["subject"]]["questions"][s["ids"][s["pos"]]]
    ok=choice in q["correct"]
    if ok: s["score"]+=1
    await c.answer()
    try: await c.message.edit_reply_markup(reply_markup=None)
    except: pass
    if s["mode"]=="train":
        if ok: await c.message.answer("✅ To‘g‘ri")
        else:
            corr=", ".join(chr(65+i) for i in q["correct"])
            await c.message.answer(f"❌ Noto‘g‘ri\n✅ To‘g‘ri javob: {corr}")
    s["pos"]+=1; await send_current(c.message,c.from_user.id)

async def main():
    token=os.getenv("BOT_TOKEN")
    if not token: raise RuntimeError("BOT_TOKEN kiritilmagan")
    await dp.start_polling(Bot(token))

if __name__=="__main__": asyncio.run(main())
