
import asyncio, json, os, random, sqlite3, time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

BASE=Path(__file__).resolve().parent
TOKEN=os.getenv("BOT_TOKEN","").strip()
DB_PATH=Path(os.getenv("DB_PATH","/data/access.db" if Path("/data").is_dir() else str(BASE/"access.db")))
DATA=json.loads((BASE/"questions.json").read_text(encoding="utf-8"))
SUBJECTS={s["key"]:s for s in DATA["subjects"]}
dp=Dispatcher()
sessions={}

def db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
        access_until TEXT, blocked INTEGER DEFAULT 0)""")
    c.commit(); return c

def touch(u):
    with db() as c:
        c.execute("""INSERT INTO users(user_id,username,full_name) VALUES(?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name""",
        (u.id,u.username or "",u.full_name or "")); c.commit()

def has_access(uid):
    if uid==ADMIN_ID and ADMIN_ID: return True
    with db() as c:
        r=c.execute("SELECT access_until,blocked FROM users WHERE user_id=?",(uid,)).fetchone()
    if not r or r[1] or not r[0]: return False
    if r[0]=="forever": return True
    try: return datetime.fromisoformat(r[0]) > datetime.now(timezone.utc)
    except: return False

def grant(uid,days=None):
    until="forever" if days is None else (datetime.now(timezone.utc)+timedelta(days=days)).isoformat()
    with db() as c:
        c.execute("""INSERT INTO users(user_id,access_until,blocked) VALUES(?,?,0)
        ON CONFLICT(user_id) DO UPDATE SET access_until=excluded.access_until,blocked=0""",(uid,until)); c.commit()
    return until

def subject_menu():
    kb=InlineKeyboardBuilder()
    for s in DATA["subjects"]: kb.button(text=s["name"],callback_data=f"sub:{s['key']}")
    kb.adjust(1); return kb.as_markup()

def mode_menu(key):
    kb=InlineKeyboardBuilder()
    kb.button(text="🧠 Заучивание",callback_data=f"mode:learn:{key}")
    kb.button(text="🔀 Тренировка",callback_data=f"mode:train:{key}")
    kb.button(text="📝 Экзамен",callback_data=f"mode:exam:{key}")
    kb.button(text="⬅️ Предметы",callback_data="home")
    kb.adjust(1); return kb.as_markup()

def answer_kb(uid,q,nonce,mode):
    kb=InlineKeyboardBuilder()
    for i,opt in enumerate(q["options"]):
        label=chr(65+i)
        kb.button(text=f"{label}. {opt[:80]}",callback_data=f"ans:{mode}:{nonce}:{i}")
    kb.adjust(1); return kb.as_markup()

async def deny(obj):
    text="🔒 Доступ не активирован.\n\nОтправьте администратору свой Telegram ID:\n<code>%s</code>"%obj.from_user.id
    if isinstance(obj,Message): await obj.answer(text,parse_mode="HTML")
    else: await obj.answer("Доступ не активирован",show_alert=True); await obj.message.answer(text,parse_mode="HTML")

@dp.message(Command("start"))
async def start(m:Message):
    touch(m.from_user)
    await m.answer("📚 Выберите предмет:",reply_markup=subject_menu())

@dp.callback_query(F.data=="home")
async def home(c:CallbackQuery):
    touch(c.from_user)
    sessions.pop(c.from_user.id,None)
    await c.message.edit_text("📚 Выберите предмет:",reply_markup=subject_menu()); await c.answer()

@dp.callback_query(F.data.startswith("sub:"))
async def sub(c:CallbackQuery):
    key=c.data.split(":",1)[1]; s=SUBJECTS[key]
    await c.message.edit_text(f"{s['name']}\n\nВ базе: {len(s['questions'])} вопросов\nВыберите режим:",reply_markup=mode_menu(key)); await c.answer()

async def send_learn(msg,uid):
    st=sessions[uid]; qs=SUBJECTS[st["subject"]]["questions"]
    if st["pos"]>=len(st["order"]):
        await msg.answer("✅ Заучивание завершено",reply_markup=subject_menu()); sessions.pop(uid,None); return
    q=qs[st["order"][st["pos"]]]
    correct=" / ".join(f"{chr(65+i)}. {q['options'][i]}" for i in q["correct"])
    opts="\n".join(f"{chr(65+i)}. {x}" for i,x in enumerate(q["options"]))
    kb=InlineKeyboardBuilder(); kb.button(text="➡️ Следующий",callback_data="learn:next"); kb.button(text="⬅️ Предметы",callback_data="home"); kb.adjust(1)
    await msg.answer(f"🧠 {st['pos']+1}/{len(st['order'])}\n\n<b>{q['question']}</b>\n\n{opts}\n\n✅ <b>Правильный ответ:</b>\n{correct}",parse_mode="HTML",reply_markup=kb.as_markup())

@dp.callback_query(F.data=="learn:next")
async def learn_next(c:CallbackQuery):
    st=sessions.get(c.from_user.id)
    if not st or st.get("mode")!="learn": return await c.answer("Сессия завершена")
    st["pos"]+=1; await c.answer(); await send_learn(c.message,c.from_user.id)

async def send_test(msg,uid):
    st=sessions[uid]; qs=SUBJECTS[st["subject"]]["questions"]
    if st["pos"]>=len(st["order"]):
        total=len(st["order"]); score=st["score"]
        title="📝 Экзамен завершён" if st["mode"]=="exam" else "🔀 Тренировка завершена"
        await msg.answer(f"{title}\n\nРезультат: <b>{score}/{total}</b> ({round(score/total*100)}%)",parse_mode="HTML",reply_markup=subject_menu())
        sessions.pop(uid,None); return
    qi=st["order"][st["pos"]]; q=qs[qi]
    nonce=str(time.time_ns())[-10:]; st["nonce"]=nonce
    if st["mode"]=="exam":
        left=max(0,2400-int(time.time()-st["started"]))
        if left<=0:
            st["pos"]=len(st["order"]); return await send_test(msg,uid)
        head=f"📝 {st['pos']+1}/{len(st['order'])} · ⏱ {left//60}:{left%60:02d}"
    else: head=f"🔀 {st['pos']+1}/{len(st['order'])}"
    await msg.answer(f"{head}\n\n<b>{q['question']}</b>",parse_mode="HTML",reply_markup=answer_kb(uid,q,nonce,st["mode"]))

@dp.callback_query(F.data.startswith("mode:"))
async def mode(c:CallbackQuery):
    _,mode,key=c.data.split(":")
    qs=SUBJECTS[key]["questions"]
    if mode=="learn":
        order=list(range(len(qs)))
        sessions[c.from_user.id]={"subject":key,"mode":"learn","order":order,"pos":0}
        await c.answer(); await send_learn(c.message,c.from_user.id); return
    if mode=="train":
        order=list(range(len(qs))); random.shuffle(order)
    else:
        order=random.sample(range(len(qs)),min(50,len(qs)))
    sessions[c.from_user.id]={"subject":key,"mode":mode,"order":order,"pos":0,"score":0,"nonce":None,"started":time.time()}
    await c.answer(); await send_test(c.message,c.from_user.id)

@dp.callback_query(F.data.startswith("ans:"))
async def ans(c:CallbackQuery):
    st=sessions.get(c.from_user.id)
    if not st: return await c.answer("Сессия завершена")
    _,mode,nonce,ixs=c.data.split(":")
    if st.get("nonce")!=nonce: return await c.answer("Этот вопрос уже отвечен")
    st["nonce"]=None
    i=int(ixs); q=SUBJECTS[st["subject"]]["questions"][st["order"][st["pos"]]]
    ok=i in q["correct"]
    if ok: st["score"]+=1
    try: await c.message.edit_reply_markup(reply_markup=None)
    except: pass
    if mode=="train":
        if ok: await c.message.answer("✅ Правильно")
        else:
            corr=" / ".join(f"{chr(65+j)}. {q['options'][j]}" for j in q["correct"])
            await c.message.answer(f"❌ Неправильно\n✅ {corr}")
    st["pos"]+=1; await c.answer()
    await send_test(c.message,c.from_user.id)


async def main():
    if not TOKEN: raise RuntimeError("BOT_TOKEN не задан")
    with db(): pass
    bot=Bot(TOKEN)
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
