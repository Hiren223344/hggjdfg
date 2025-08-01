import requests
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
A4F_API_KEY = os.getenv("A4F_API_KEY")

user_model = {}

model_map = {
    "4o": "provider-6/gpt-4o-mini-search-preview",
    "gemini": "provider-6/gemini-2.5-flash",
    "deepseek": "provider-1/deepseek-r1-0528",
    "mistral": "provider-1/mistral-large",
    "image": "provider-1/FLUX.1-kontext-pro",
    "video": "provider-6/wan-2.1"
}

def get_keyboard():
    keyboard = []
    for key in model_map:
        keyboard.append([InlineKeyboardButton(key.capitalize(), callback_data=f"select_{key}")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Our Models:\nType /modelname to select or use the buttons below.",
        reply_markup=get_keyboard()
    )

async def select_model_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_key = query.data.replace("select_", "")
    user_id = query.from_user.id

    if selected_key in model_map:
        user_model[user_id] = selected_key
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f'✅ Model selected "{selected_key}"'
        )
    else:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚠️ Invalid model selection."
        )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text.replace("/", "").lower()
    if cmd in model_map:
        user_model[update.message.from_user.id] = cmd
        await update.message.reply_text(f'✅ Model selected "{cmd}"')
    else:
        await update.message.reply_text("⚠️ Invalid model. Use /start to see available models.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    if user_id not in user_model:
        await context.bot.send_message(chat_id, "⚠️ Please select a model first using /start")
        return

    selected_key = user_model[user_id]
    selected_model = model_map[selected_key]
    user_message = update.message.text

    # Handle image generation
    if selected_key == "image":
        await context.bot.send_message(chat_id, "🖼 Generating image, please wait...")
        try:
            client = OpenAI(
                api_key=A4F_API_KEY,
                base_url="https://api.a4f.co/v1"
            )
            response = client.images.generate(
                model=selected_model,
                prompt=user_message,
                n=1,
                size="1024x1024"
            )
            image_url = response.data[0].url
            await context.bot.send_photo(chat_id, image_url, caption="Here is your generated image!")
        except Exception as e:
            await context.bot.send_message(chat_id, f"⚠️ Error generating image: {e}")
        return

    # Handle video generation
    if selected_key == "video":
        await context.bot.send_message(chat_id, "🎬 Generating video, please wait...")
        headers = {
            'Authorization': f'Bearer {A4F_API_KEY}',
            'Content-Type': 'application/json',
        }
        json_data = {
            'model': selected_model,
            'prompt': user_message,
            'ratio': '16:9',
            'quality': '480p',  # Free plan supported
            'duration': 4,
        }
        try:
            response = requests.post(
                'https://api.a4f.co/v1/video/generations',
                headers=headers,
                json=json_data
            )
            if response.status_code == 200:
                data = response.json()
                video_url = data.get('data', [{}])[0].get('url') or data.get('url')
                if video_url:
                    await context.bot.send_video(chat_id, video_url, caption="Here is your generated video!")
                else:
                    await context.bot.send_message(chat_id, f"⚠️ Video generated but no URL found:\n{json.dumps(data, indent=2)}")
            else:
                await context.bot.send_message(chat_id, f"⚠️ Error: {response.status_code}\n{response.text}")
        except Exception as e:
            await context.bot.send_message(chat_id, f"⚠️ Error generating video: {e}")
        return

    # Handle text models
    response = requests.post(
        url="https://api.a4f.co/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {A4F_API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "model": selected_model,
            "messages": [{"role": "user", "content": user_message}]
        })
    )

    try:
        ai_reply = response.json()['choices'][0]['message']['content']
    except Exception:
        ai_reply = "⚠️ Error: Couldn't process your message."

    await context.bot.send_message(chat_id, ai_reply)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    file_id = None
    if update.message.voice:
        file_id = update.message.voice.file_id
    elif update.message.audio:
        file_id = update.message.audio.file_id

    if not file_id:
        await context.bot.send_message(chat_id, "⚠️ No audio file found.")
        return

    file = await context.bot.get_file(file_id)
    audio_path = f"temp_{user_id}.ogg"
    await file.download_to_drive(audio_path)

    try:
        client = OpenAI(
            api_key=A4F_API_KEY,
            base_url="https://api.a4f.co/v1"
        )
        # Transcription
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="provider-2/whisper-1",
                file=audio_file
            )
        await context.bot.send_message(chat_id, f"📝 Transcription:\n{transcript.text}")

        # Text-to-Speech (TTS) - generate audio from the transcription
        tts_response = client.audio.speech.create(
            model="provider-6/sonic-2",
            voice="alloy",
            input=transcript.text
        )
        tts_path = f"tts_{user_id}.mp3"
        tts_response.stream_to_file(tts_path)
        with open(tts_path, "rb") as tts_audio:
            await context.bot.send_audio(chat_id, tts_audio, caption="🔊 Text-to-Speech Audio")
    except Exception as e:
        await context.bot.send_message(chat_id, f"⚠️ Error transcribing or generating audio: {e}")
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if 'tts_path' in locals() and os.path.exists(tts_path):
            os.remove(tts_path)

async def show_model_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Select a model:",
        reply_markup=get_keyboard()
    )

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("models", show_model_selector))  # <-- Add this line
    app.add_handler(CallbackQueryHandler(select_model_button, pattern="^select_"))
    for key in model_map:
        app.add_handler(CommandHandler(key, model_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, handle_audio))
    print("Bot Started")
    app.run_polling()
