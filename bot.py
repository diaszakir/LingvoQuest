import telebot
from pymongo import MongoClient
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import csv
import random
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient("mongodb://localhost:27017/")
db = client["lingvoquest"]
users_collection = db["users"]

token = os.getenv("TELEGRAM_BOT_API_TOKEN")
bot = telebot.TeleBot(token)

def load_words_from_csv(file_path):
    words = []
    try:
        with open(file_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                words.append({"word": row["word"], "meaning": row["meaning"]})
    except FileNotFoundError:
        print(f"Файл {file_path} не найден.")
    return words

all_words = load_words_from_csv("words.csv")

@bot.message_handler(commands=["start"])
def start_command(message):
    user_id = message.chat.id
    if not users_collection.find_one({"user_id": user_id}):
        users_collection.insert_one({"user_id": user_id, "words": [], "current_word_index": 0})
        bot.send_message(user_id, "Добро пожаловать в LingvoQuest! 🚀")
    else:
        bot.send_message(user_id, "С возвращением! Используй /help, чтобы увидеть список команд.")
    show_main_menu(message)

def show_main_menu(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📚 Изучить слово", "📝 Тренировка")
    markup.add("📖 Мои слова", "ℹ️ Помощь")
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(commands=["learn_word"])
@bot.message_handler(func=lambda message: message.text == "📚 Изучить слово")
def learn_word(message):
    user_id = message.chat.id
    user = users_collection.find_one({"user_id": user_id})

    if not all_words:
        bot.send_message(user_id, "Список слов пуст. Добавьте слова в файл words.csv.")
        return

    current_index = user.get("current_word_index", 0)
    if current_index >= len(all_words):
        bot.send_message(user_id, "Вы изучили все доступные слова! 🎉")
        return

    word_data = all_words[current_index]
    word = word_data["word"]
    meaning = word_data["meaning"]

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Продолжить", callback_data=f"learn_continue:{current_index + 1}"),
        InlineKeyboardButton("Остановиться", callback_data="learn_stop")
    )
    bot.send_message(
        user_id,
        f"Слово: {word}\nЗначение: {meaning}\nХотите продолжить?",
        reply_markup=markup
    )
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"current_word_index": current_index + 1}, "$addToSet": {"words": {"word": word, "meaning": meaning}}}
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("learn"))
def handle_learn_callbacks(call):
    user_id = call.message.chat.id
    if call.data.startswith("learn_continue"):
        learn_word(call.message)
    elif call.data == "learn_stop":
        bot.send_message(user_id, "Изучение остановлено. Возвращайтесь в любое время! 😊")

def generate_test_questions(user_words, num_questions=5):
    sampled_words = random.sample(user_words, min(num_questions, len(user_words)))
    questions = []
    for word in sampled_words:
        correct = word["meaning"]
        incorrect = random.sample(
            [w["meaning"] for w in user_words if w["meaning"] != correct],
            k=min(3, len(user_words) - 1)
        )
        options = incorrect + [correct]
        random.shuffle(options)
        questions.append({"word": word["word"], "options": options, "correct": correct})
    return questions


@bot.message_handler(commands=["start_test"])
@bot.message_handler(func=lambda message: message.text == "📝 Тренировка")
def start_test(message):
    user_id = message.chat.id
    user = users_collection.find_one({"user_id": user_id})
    user_words = user.get("words", [])
    if len(user_words) < 5:
        bot.send_message(user_id, "Недостаточно изученных слов для теста (минимум 5).")
        return

    questions = generate_test_questions(user_words)
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"current_test": questions, "current_question_index": 0, "correct_answers": 0}}
    )
    send_test_question(user_id)


def send_test_question(user_id):
    user = users_collection.find_one({"user_id": user_id})
    questions = user.get("current_test", [])
    index = user.get("current_question_index", 0)
    if index >= len(questions):
        finish_test(user_id)
        return

    question = questions[index]
    word = question["word"]
    options = question["options"]
    markup = InlineKeyboardMarkup()
    for i, option in enumerate(options):
        markup.add(InlineKeyboardButton(option, callback_data=f"test_answer:{i}"))
    bot.send_message(user_id, f"Что означает слово '{word}'?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("test_answer"))
def handle_test_answer(call):
    user_id = call.message.chat.id
    user = users_collection.find_one({"user_id": user_id})
    questions = user.get("current_test", [])
    index = user.get("current_question_index", 0)
    question = questions[index]
    selected = int(call.data.split(":")[1])
    selected_option = question["options"][selected]

    if selected_option == question["correct"]:
        bot.answer_callback_query(call.id, "Правильно! ✅")
        users_collection.update_one({"user_id": user_id}, {"$inc": {"correct_answers": 1}})
    else:
        bot.answer_callback_query(call.id, f"Неправильно. Правильный ответ: {question['correct']}.")

    users_collection.update_one({"user_id": user_id}, {"$inc": {"current_question_index": 1}})
    send_test_question(user_id)

def finish_test(user_id):
    user = users_collection.find_one({"user_id": user_id})
    correct = user.get("correct_answers", 0)
    total = len(user.get("current_test", []))
    bot.send_message(user_id, f"Тест завершён! ✅ Результат: {correct}/{total}.")
    users_collection.update_one({"user_id": user_id}, {"$unset": {"current_test": "", "current_question_index": "", "correct_answers": ""}})


@bot.message_handler(commands=["view_words"])
@bot.message_handler(func=lambda message: message.text == "📖 Мои слова")
def view_words(message):
    user_id = message.chat.id
    user = users_collection.find_one({"user_id": user_id})
    user_words = user.get("words", [])

    if not user_words:
        bot.send_message(user_id, "Вы ещё не изучили ни одного слова.")
        return

    send_words_page(user_id, user_words, page=1)

def send_words_page(user_id, words, page=1):
    words_per_page = 15
    total_words = len(words)
    total_pages = (total_words + words_per_page - 1) // words_per_page

    if page < 1 or page > total_pages:
        bot.send_message(user_id, "Такой страницы не существует.")
        return

    start_index = (page - 1) * words_per_page
    end_index = start_index + words_per_page
    words_on_page = words[start_index:end_index]

    message_text = f"Изученные слова (страница {page}/{total_pages}):\n\n"
    for i, word in enumerate(words_on_page, start=start_index + 1):
        message_text += f"{i}. {word['word']} - {word['meaning']}\n"

    markup = InlineKeyboardMarkup()
    if page > 1:
        markup.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"view_page:{page-1}"))
    if page < total_pages:
        markup.add(InlineKeyboardButton("Вперёд ➡️", callback_data=f"view_page:{page+1}"))

    bot.send_message(user_id, message_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_page"))
def handle_view_page(call):
    user_id = call.message.chat.id
    user = users_collection.find_one({"user_id": user_id})
    user_words = user.get("words", [])
    page = int(call.data.split(":")[1])
    send_words_page(user_id, user_words, page)

@bot.message_handler(commands=["help"])
@bot.message_handler(func=lambda message: message.text == "ℹ️ Помощь")
def help_command(message):
    bot.send_message(
        message.chat.id,
        "Доступные команды:\n"
        "/learn_word - Изучить новое слово\n"
        "/view_words - Просмотр изученных слов\n"
        "/start_test - Пройти тест по изученным словам"
    )

if __name__ == "__main__":
    bot.polling(none_stop=True)
