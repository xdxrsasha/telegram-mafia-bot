from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import random
import asyncio
from flask import Flask, request
import os

app = Flask(__name__)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8042974218:AAFrxiU3uPBgWyDmpO9L1Obl0n_M8bhAbfI")

# Инициализация Application один раз при старте
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("game", start_game))
application.add_handler(CommandHandler("stop", stop_game))
application.add_handler(CallbackQueryHandler(join_game, pattern="join_game"))
application.add_handler(CallbackQueryHandler(handle_night_action, pattern="^(kill|heal|check|love)_"))
application.add_handler(CallbackQueryHandler(handle_vote, pattern="^vote_"))

game_states = {}

def get_game_state(chat_id):
    if chat_id not in game_states:
        game_states[chat_id] = {
            "players": {},
            "game_running": False,
            "phase": None,
            "roles": ["Мафия", "Доктор", "Детектив", "Мирный", "Любовница"],
            "night_actions": {},
            "votes": {},
            "start_message_id": None,
            "bot_player": {"username": "BotMafia", "role": None, "alive": True},
            "lover_pairs": {}
        }
    return game_states[chat_id]

async def create_join_button():
    keyboard = [[InlineKeyboardButton("Присоединиться", callback_data="join_game")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def create_night_buttons(players, action):
    keyboard = [[InlineKeyboardButton(info["username"], callback_data=f"{action}_{user_id}")] for user_id, info in players.items() if info["alive"]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def create_vote_buttons(players):
    keyboard = [[InlineKeyboardButton(info["username"], callback_data=f"vote_{user_id}")] for user_id, info in players.items() if info["alive"]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat_id = update.message.chat_id
    game_state = get_game_state(chat_id)
    if game_state["game_running"]:
        await update.message.reply_text("Игра уже идёт! Дождитесь её окончания.")
        return
    game_state["game_running"] = True
    game_state["players"] = {}
    game_state["phase"] = None
    game_state["lover_pairs"] = {}
    try:
        message = await update.message.reply_text(f"Набор в игру 'Мафия' начался в чате '{update.message.chat.title}'! Нажмите кнопку, чтобы присоединиться. Минимум 4 игрока.", reply_markup=await create_join_button())
        game_state["start_message_id"] = message.message_id
    except Exception as e:
        print(f"Ошибка: {e}")

async def stop_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat_id = update.message.chat_id
    game_state = get_game_state(chat_id)
    if not game_state["game_running"]:
        await update.message.reply_text("Игра не активна!")
        return
    game_state["game_running"] = False
    game_state["phase"] = None
    game_state["players"] = {}
    game_state["night_actions"] = {}
    game_state["votes"] = {}
    game_state["lover_pairs"] = {}
    game_state["start_message_id"] = None
    try:
        await update.message.reply_text(f"Игра остановлена администратором в чате '{update.message.chat.title}'!")
    except Exception as e:
        print(f"Ошибка: {e}")

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.message is None:
        return
    chat_id = update.callback_query.message.chat_id
    game_state = get_game_state(chat_id)
    if not game_state["game_running"]:
        await update.callback_query.answer("Игра не активна!")
        return
    user_id = update.callback_query.from_user.id
    display_name = update.callback_query.from_user.first_name
    username = update.callback_query.from_user.username or display_name
    if user_id in game_state["players"]:
        await update.callback_query.answer("Ты уже в игре!")
        return
    game_state["players"][user_id] = {"username": username, "role": None, "alive": True}
    if len(game_state["players"]) < 4:
        game_state["players"]["bot_id"] = game_state["bot_player"]
    mention = f"<a href=\"tg://user?id={user_id}\">{display_name}</a>"
    player_count = len(game_state["players"])
    new_text = f"Набор в игру 'Мафия' начался в чате '{update.callback_query.message.chat.title}'! Присоединились: {mention} (игроков: {player_count}). Минимум 4 игрока."
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=game_state["start_message_id"],
            text=new_text,
            reply_markup=await create_join_button(),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка: {e}")
    await update.callback_query.answer(f"{display_name}, ты присоединился к игре!")
    if len(game_state["players"]) >= 4:
        await assign_roles(context, chat_id)
        await start_night(context, chat_id)

async def assign_roles(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game_state = get_game_state(chat_id)
    players = list(game_state["players"].keys())
    random.shuffle(players)
    num_players = len(players)
    roles = game_state["roles"].copy()
    random.shuffle(roles)
    while len(roles) < num_players:
        roles.append("Мирный")
    roles = roles[:num_players]
    for i, user_id in enumerate(players):
        game_state["players"][user_id]["role"] = roles[i]
        try:
            await context.bot.send_message(user_id if user_id != "bot_id" else chat_id, f"Роль {game_state['players'][user_id]['username']} : {roles[i]}")
        except Exception as e:
            print(f"Ошибка: {e}")

async def start_night(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game_state = get_game_state(chat_id)
    game_state["phase"] = "night"
    game_state["night_actions"] = {}
    alive_players = {k: v for k, v in game_state["players"].items() if v["alive"]}
    alive_list = ", ".join([info["username"] for info in alive_players.values()])
    await context.bot.send_message(chat_id, f"Ночь началась! Живые игроки: {alive_list}")
    for user_id, info in alive_players.items():
        role = info["role"]
        if user_id != "bot_id":
            if role == "Мафия":
                await context.bot.send_message(user_id, "Кого убить?", reply_markup=await create_night_buttons(alive_players, "kill"))
            elif role == "Доктор":
                await context.bot.send_message(user_id, "Кого вылечить?", reply_markup=await create_night_buttons(alive_players, "heal"))
            elif role == "Детектив":
                await context.bot.send_message(user_id, "Кого проверить?", reply_markup=await create_night_buttons(alive_players, "check"))
            elif role == "Любовница":
                await context.bot.send_message(user_id, "Кого заблокировать или выбрать партнёра?", reply_markup=await create_night_buttons(alive_players, "love"))
    await asyncio.sleep(30)
    await resolve_night(context, chat_id)

async def handle_night_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.message is None:
        return
    chat_id = update.callback_query.message.chat_id
    game_state = get_game_state(chat_id)
    if game_state["phase"] != "night":
        await update.callback_query.answer("Сейчас не ночь!")
        return
    user_id = update.callback_query.from_user.id
    if user_id not in game_state["players"] or not game_state["players"][user_id]["alive"]:
        await update.callback_query.answer("Ты не можешь действовать!")
        return
    action, target_id = update.callback_query.data.split("_")
    target_id = int(target_id)
    game_state["night_actions"][user_id] = {"action": action, "target": target_id}
    await update.callback_query.answer("Выбор принят!")

async def resolve_night(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game_state = get_game_state(chat_id)
    kill_target = None
    heal_target = None
    check_result = None
    block_target = None

    for user_id, action in game_state["night_actions"].items():
        role = game_state["players"][user_id]["role"]
        if action["action"] == "kill" and role == "Мафия":
            kill_target = action["target"]
        elif action["action"] == "heal" and role == "Доктор":
            heal_target = action["target"]
        elif action["action"] == "check" and role == "Детектив":
            check_result = {"detective": user_id, "target": action["target"]}
        elif action["action"] == "love" and role == "Любовница":
            target_id = action["target"]
            if target_id in game_state["lover_pairs"] and game_state["lover_pairs"][target_id] == user_id:
                await context.bot.send_message(user_id, "Вы уже пара!")
            elif user_id not in game_state["lover_pairs"]:
                game_state["lover_pairs"][user_id] = target_id
                game_state["lover_pairs"][target_id] = user_id
                await context.bot.send_message(user_id, f"Ты выбрал партнёра {game_state['players'][target_id]['username']}!")
                await context.bot.send_message(target_id, f"Тебя выбрал в пару {game_state['players'][user_id]['username']}!")
            else:
                block_target = target_id
                await context.bot.send_message(user_id, f"Ты заблокировал {game_state['players'][target_id]['username']} на эту ночь!")

    if check_result:
        target_role = game_state["players"][check_result["target"]]["role"]
        await context.bot.send_message(check_result["detective"], f"Роль игрока: {target_role}")
    if kill_target and kill_target != heal_target and kill_target != block_target:
        game_state["players"][kill_target]["alive"] = False
        username = game_state["players"][kill_target]["username"]
        if kill_target in game_state["lover_pairs"] and game_state["lover_pairs"][kill_target] in game_state["players"]:
            lover_id = game_state["lover_pairs"][kill_target]
            game_state["players"][lover_id]["alive"] = False
            await context.bot.send_message(chat_id, f"{username} убит! Его любовник {game_state['players'][lover_id]['username']} умер от горя!")
        else:
            await context.bot.send_message(chat_id, f"{username} убит!")
    await start_day(context, chat_id)

async def start_day(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game_state = get_game_state(chat_id)
    game_state["phase"] = "day"
    game_state["votes"] = {}
    alive_players = {k: v for k, v in game_state["players"].items() if v["alive"]}
    if len(alive_players) <= 2:
        await end_game(context, chat_id)
        return
    alive_list = ", ".join([info["username"] for info in alive_players.values()])
    await context.bot.send_message(chat_id, f"День начался! Живые игроки: {alive_list}\nКого повесить?", reply_markup=await create_vote_buttons(alive_players))
    await asyncio.sleep(30)
    await resolve_day(context, chat_id)

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.message is None:
        return
    chat_id = update.callback_query.message.chat_id
    game_state = get_game_state(chat_id)
    if game_state["phase"] != "day":
        await update.callback_query.answer("Сейчас не день!")
        return
    user_id = update.callback_query.from_user.id
    if user_id not in game_state["players"] or not game_state["players"][user_id]["alive"]:
        await update.callback_query.answer("Ты не можешь голосовать!")
        return
    target_id = int(update.callback_query.data.split("_")[1])
    game_state["votes"][user_id] = target_id
    await update.callback_query.answer("Голос учтён!")

async def resolve_day(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game_state = get_game_state(chat_id)
    if not game_state["votes"]:
        await context.bot.send_message(chat_id, "Никто не проголосовал. Ночь начинается.")
        await start_night(context, chat_id)
        return
    vote_counts = {}
    for target_id in game_state["votes"].values():
        vote_counts[target_id] = vote_counts.get(target_id, 0) + 1
    max_votes = max(vote_counts.values(), default=0)
    if max_votes > len(game_state["players"]) // 2:
        lynched_id = max(vote_counts, key=vote_counts.get)
        game_state["players"][lynched_id]["alive"] = False
        username = game_state["players"][lynched_id]["username"]
        if lynched_id in game_state["lover_pairs"] and game_state["lover_pairs"][lynched_id] in game_state["players"]:
            lover_id = game_state["lover_pairs"][lynched_id]
            game_state["players"][lover_id]["alive"] = False
            await context.bot.send_message(chat_id, f"{username} повешен! Его любовник {game_state['players'][lover_id]['username']} умер от горя!")
        else:
            await context.bot.send_message(chat_id, f"{username} повешен!")
    else:
        await context.bot.send_message(chat_id, "Никто не получил большинства.")
    await start_night(context, chat_id)

async def end_game(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game_state = get_game_state(chat_id)
    await context.bot.send_message(chat_id, "Игра окончена!")
    game_state["game_running"] = False
    game_state["phase"] = None
    game_state["players"] = {}
    game_state["start_message_id"] = None
    game_state["lover_pairs"] = {}

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), application)
    application.process_update(update)
    return "OK"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
