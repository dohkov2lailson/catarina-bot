import os
import logging
import requests
import json
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction

# ─── CONFIG ───
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── BRAND PRESETS ───
BRANDS = {
    "llsquad": {
        "name": "🏋️ LL Squad",
        "prompt": (
            "IDENTIDADE DA MARCA:\n"
            "Marca: LL Squad — Personal Trainers\n"
            "@llsquad.fit | Inove Fit, Pelinca, Campos dos Goytacazes/RJ\n"
            "Cores: Preto #0A0A0A, Laranja #FF6B00, Roxo neon #A855F7, Branco #E8E8E8\n"
            "Tom: Motivacional, direto, profissional com toque pessoal. Linguagem fitness acessível.\n"
            "Público: Homens e mulheres 20-45, praticantes de musculação.\n"
            "Estilo visual: Dark/tech, fundo escuro, acentos vibrantes, tipografia bold, iluminação dramática.\n"
            "Slogan: Seu shape, nosso método.\n"
            "Diferencial: Método PPS (MTOR-based), consultoria online e presencial híbrida."
        )
    },
    "melliz": {
        "name": "🏛️ Melliz Arquitetura",
        "prompt": (
            "IDENTIDADE DA MARCA:\n"
            "Marca: Melliz Arquitetura\n"
            "@melliz.arquitetura | Posicionamento: \"Seu espaço encanta?\"\n"
            "Cores: Off-white #FAF8F5, Verde oliva #5C6B4F, Bege quente #C4A882, Grafite #2C2C2C, Dourado sutil #B8976A\n"
            "Tom: Sofisticado e clean, inspiracional sem ser pretensioso.\n"
            "Público: Mulheres e casais 25-45, classe média-alta, construindo/reformando/decorando.\n"
            "Estilo visual: Minimalista, fotos claras com luz natural, tons terrosos e neutros, muito espaço negativo.\n"
            "Diferencial: Projetos que conectam emoção e funcionalidade."
        )
    }
}

CATARINA_SYSTEM = """Você é a Catarina, gerente de marketing do LL Squad — equipe de personal trainers liderada pelo Lailson Lima, dono da academia Inove Fit em Campos dos Goytacazes/RJ.

Você é especialista em criação de conteúdo para Instagram. Também cria conteúdo para outras marcas quando recebe a identidade visual.

Regras por formato:

POST SIMPLES:
- Título curto e chamativo
- Texto principal curto e escaneável
- Sugestão visual para a imagem do post
- Prompt detalhado para gerar a imagem em IA (em inglês, formato vertical 4:5, sem texto na imagem)
- Legenda otimizada para Instagram
- Entre 5 e 8 hashtags relevantes

CARROSSEL (6 a 8 slides):
- Para cada slide: Título, Texto curto, Sugestão visual, Prompt para imagem (em inglês)
- Slide 1 = capa com forte curiosidade
- Demais slides: infográficos, ícones, diagramas, elementos educativos

REELS:
- Gancho inicial forte (primeiros 3 segundos)
- Explicação em 3 ou 4 pontos
- Fechamento com call to action
- Sugestão visual das cenas
- Legenda
- Hashtags

Regras gerais:
- Sempre responda em português do Brasil
- Seja criativa, linguagem conectada ao público-alvo da marca
- Tom: profissional mas descontraído, motivacional sem ser clichê
- Foque em storytelling e ativação de desejo através de dores
- Evite temas básicos e clichês
- Prompts de imagem sempre em inglês
- Nunca inclua texto/tipografia dentro das imagens descritas nos prompts"""

FORMAT_LABELS = {
    "post": "📸 Post Simples",
    "carrossel": "🎠 Carrossel (6-8 slides)",
    "reels": "🎬 Reels (Roteiro)"
}

# ─── USER STATE ───
user_states = {}

def get_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            "brand": "llsquad",
            "format": None,
            "waiting_for": None,
            "custom_brand": "",
            "_pending_tema": "",
            "_pending_images": None,
            "_pending_pdf": None,
        }
    return user_states[user_id]


# ─── ANTHROPIC CALL VIA REQUESTS (no SDK) ───
def call_catarina(user_message, brand_key, format_key, custom_brand="", images=None, pdf_data=None):
    brand_prompt = ""
    if brand_key == "custom" and custom_brand:
        brand_prompt = f"\n\nIDENTIDADE DA MARCA:\n{custom_brand}"
    elif brand_key in BRANDS:
        brand_prompt = f"\n\n{BRANDS[brand_key]['prompt']}"

    format_label = FORMAT_LABELS.get(format_key, "Post Simples")

    # Build content
    content = []

    if images:
        for img in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"]
                }
            })

    if pdf_data:
        pdf_b64 = base64.b64encode(pdf_data).decode("utf-8")
        content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64
            }
        })

    full_text = f"{brand_prompt}\n\nFormato solicitado: {format_label}\n\n{user_message}"
    content.append({"type": "text", "text": full_text})

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "system": CATARINA_SYSTEM,
        "messages": [{"role": "user", "content": content}]
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
    }

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=120
    )

    if resp.status_code != 200:
        error_msg = resp.json().get("error", {}).get("message", resp.text[:200])
        raise Exception(f"API error {resp.status_code}: {error_msg}")

    data = resp.json()
    text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    if not text_parts:
        raise Exception("Resposta vazia da API")

    return "\n".join(text_parts)


# ─── HANDLERS ───

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = get_state(user.id)
    state["waiting_for"] = None

    welcome = (
        f"👋 Oi, *{user.first_name}*! Eu sou a *Catarina*, sua gerente de marketing.\n\n"
        "Eu crio conteúdo profissional pro Instagram — posts, carrosséis e reels — "
        "adaptados à identidade da marca que você escolher.\n\n"
        "🏋️ *LL Squad* (padrão)\n"
        "🏛️ *Melliz Arquitetura*\n"
        "✨ *Marca personalizada*\n\n"
        "📌 *Comandos:*\n"
        "/criar — Criar conteúdo novo\n"
        "/marca — Trocar a marca\n"
        "/ajuda — Ver todos os comandos\n\n"
        "Ou me manda o tema direto que eu já crio! 🚀"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Comandos da Catarina:*\n\n"
        "/criar — Iniciar criação de conteúdo\n"
        "/marca — Escolher/trocar a marca\n"
        "/post `tema` — Gerar post direto\n"
        "/carrossel `tema` — Gerar carrossel direto\n"
        "/reels `tema` — Gerar reels direto\n"
        "/ajuda — Esta mensagem\n\n"
        "💡 *Dicas:*\n"
        "• Envie uma *foto* junto com o tema pra eu usar como referência visual\n"
        "• Envie um *PDF* que eu transformo em conteúdo pro Instagram\n"
        "• Pode mandar o tema direto sem comando — eu pergunto o formato"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏋️ LL Squad", callback_data="brand_llsquad")],
        [InlineKeyboardButton("🏛️ Melliz Arquitetura", callback_data="brand_melliz")],
        [InlineKeyboardButton("✨ Outra marca", callback_data="brand_custom")],
    ]
    await update.message.reply_text(
        "🎨 *Escolha a marca:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_criar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_state(update.effective_user.id)
    brand_name = BRANDS.get(state["brand"], {}).get("name", "✨ Personalizada")

    keyboard = [
        [InlineKeyboardButton("📸 Post", callback_data="fmt_post")],
        [InlineKeyboardButton("🎠 Carrossel", callback_data="fmt_carrossel")],
        [InlineKeyboardButton("🎬 Reels", callback_data="fmt_reels")],
    ]
    await update.message.reply_text(
        f"🎯 *Qual formato?*\nMarca ativa: {brand_name}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_direto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.split()[0].replace("/", "")
    tema = update.message.text.replace(f"/{command}", "").strip()
    state = get_state(update.effective_user.id)

    if not tema:
        state["format"] = command
        state["waiting_for"] = "tema"
        await update.message.reply_text(
            f"✏️ Manda o tema pro *{FORMAT_LABELS[command]}*:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    state["format"] = command
    await gerar_conteudo(update, tema, state)


# ─── CALLBACKS ───

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = get_state(user_id)
    data = query.data

    if data.startswith("brand_"):
        brand = data.replace("brand_", "")
        state["brand"] = brand

        if brand == "custom":
            state["waiting_for"] = "brand_text"
            await query.edit_message_text(
                "✨ *Marca personalizada*\n\n"
                "Me manda as infos da marca:\n"
                "Nome, cores, tom de voz, público, estilo visual...",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            brand_name = BRANDS[brand]["name"]
            await query.edit_message_text(
                f"✅ Marca: *{brand_name}*\n\nAgora use /criar ou mande um tema!",
                parse_mode=ParseMode.MARKDOWN
            )

    elif data.startswith("fmt_"):
        fmt = data.replace("fmt_", "")
        state["format"] = fmt

        # Check for pending data
        if state.get("waiting_for") == "_pending" and state.get("_pending_tema"):
            tema = state.pop("_pending_tema", "")
            state["waiting_for"] = None
            await query.edit_message_text(f"⚡ Gerando *{FORMAT_LABELS[fmt]}*...", parse_mode=ParseMode.MARKDOWN)
            await gerar_conteudo(update, tema, state)
            return

        state["waiting_for"] = "tema"
        await query.edit_message_text(
            f"✏️ Manda o *tema* pro {FORMAT_LABELS[fmt]}:\n\n"
            "💡 Pode mandar texto, foto ou PDF!",
            parse_mode=ParseMode.MARKDOWN
        )

    elif data == "show_formats":
        keyboard = [
            [InlineKeyboardButton("📸 Post", callback_data="fmt_post")],
            [InlineKeyboardButton("🎠 Carrossel", callback_data="fmt_carrossel")],
            [InlineKeyboardButton("🎬 Reels", callback_data="fmt_reels")],
        ]
        await query.edit_message_text(
            "🎯 *Qual formato?*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

    elif data == "show_brands":
        keyboard = [
            [InlineKeyboardButton("🏋️ LL Squad", callback_data="brand_llsquad")],
            [InlineKeyboardButton("🏛️ Melliz Arquitetura", callback_data="brand_melliz")],
            [InlineKeyboardButton("✨ Outra marca", callback_data="brand_custom")],
        ]
        await query.edit_message_text(
            "🎨 *Escolha a marca:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )


# ─── MESSAGE HANDLER ───

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_state(user_id)
    text = update.message.text or ""

    if state["waiting_for"] == "brand_text":
        state["custom_brand"] = text
        state["waiting_for"] = None
        await update.message.reply_text(
            "✅ Marca personalizada salva!\n\nUse /criar ou mande um tema.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if state["waiting_for"] == "tema" and state["format"]:
        await gerar_conteudo(update, text, state)
        return

    if text.strip():
        state["_pending_tema"] = text
        state["waiting_for"] = "_pending"
        brand_name = BRANDS.get(state["brand"], {}).get("name", "✨ Personalizada")
        keyboard = [
            [
                InlineKeyboardButton("📸 Post", callback_data="fmt_post"),
                InlineKeyboardButton("🎠 Carrossel", callback_data="fmt_carrossel"),
                InlineKeyboardButton("🎬 Reels", callback_data="fmt_reels"),
            ]
        ]
        await update.message.reply_text(
            f"💡 *Tema recebido!*\nMarca: {brand_name}\n\n🎯 Qual formato?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_state(user_id)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()
    photo_b64 = base64.b64encode(bytes(photo_bytes)).decode("utf-8")

    caption = update.message.caption or ""

    state["_pending_tema"] = caption or "Crie conteúdo baseado nesta imagem de referência"
    state["_pending_images"] = [{"media_type": "image/jpeg", "data": photo_b64}]
    state["waiting_for"] = "_pending"

    brand_name = BRANDS.get(state["brand"], {}).get("name", "✨ Personalizada")
    keyboard = [
        [
            InlineKeyboardButton("📸 Post", callback_data="fmt_post"),
            InlineKeyboardButton("🎠 Carrossel", callback_data="fmt_carrossel"),
            InlineKeyboardButton("🎬 Reels", callback_data="fmt_reels"),
        ]
    ]
    await update.message.reply_text(
        f"📷 *Referência recebida!*\nMarca: {brand_name}\n\n🎯 Qual formato?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_state(user_id)
    doc = update.message.document

    if doc.mime_type != "application/pdf":
        await update.message.reply_text("⚠️ Envie um arquivo PDF.")
        return
    if doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("⚠️ Máximo 10MB.")
        return

    file = await context.bot.get_file(doc.file_id)
    pdf_bytes = await file.download_as_bytearray()

    caption = update.message.caption or ""

    state["_pending_tema"] = caption or "Transforme este PDF em conteúdo para Instagram"
    state["_pending_pdf"] = bytes(pdf_bytes)
    state["waiting_for"] = "_pending"

    brand_name = BRANDS.get(state["brand"], {}).get("name", "✨ Personalizada")
    keyboard = [
        [
            InlineKeyboardButton("📸 Post", callback_data="fmt_post"),
            InlineKeyboardButton("🎠 Carrossel", callback_data="fmt_carrossel"),
            InlineKeyboardButton("🎬 Reels", callback_data="fmt_reels"),
        ]
    ]
    await update.message.reply_text(
        f"📄 *PDF recebido!* ({doc.file_name})\nMarca: {brand_name}\n\n🎯 Qual formato?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ─── GENERATE ───

async def gerar_conteudo(update: Update, tema: str, state: dict, images=None, pdf_data=None):
    if images is None:
        images = state.pop("_pending_images", None)
    if pdf_data is None:
        pdf_data = state.pop("_pending_pdf", None)

    fmt = state.get("format", "post")
    brand = state.get("brand", "llsquad")
    custom_brand = state.get("custom_brand", "")

    msg = update.message or update.callback_query.message
    brand_name = BRANDS.get(brand, {}).get("name", "✨ Personalizada")
    fmt_label = FORMAT_LABELS.get(fmt, "Post")

    await msg.reply_chat_action(ChatAction.TYPING)

    status = await msg.reply_text(
        f"⚡ *Gerando {fmt_label}...*\nMarca: {brand_name}\n\n_Catarina trabalhando..._",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        result = call_catarina(
            user_message=f"Tema: \"{tema}\"\nFormato: {fmt_label}\n\nGere o conteúdo completo.",
            brand_key=brand,
            format_key=fmt,
            custom_brand=custom_brand,
            images=images,
            pdf_data=pdf_data
        )

        await status.delete()

        if len(result) <= 4000:
            try:
                await msg.reply_text(result, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await msg.reply_text(result)
        else:
            for chunk in split_message(result, 4000):
                try:
                    await msg.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await msg.reply_text(chunk)

        keyboard = [
            [
                InlineKeyboardButton("🔄 Outro tema", callback_data=f"fmt_{fmt}"),
                InlineKeyboardButton("🎯 Outro formato", callback_data="show_formats"),
            ],
            [InlineKeyboardButton("🎨 Trocar marca", callback_data="show_brands")],
        ]
        await msg.reply_text(
            "✅ *Pronto!* O que quer fazer agora?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await status.edit_text(
            f"❌ *Erro:*\n`{str(e)[:300]}`",
            parse_mode=ParseMode.MARKDOWN
        )

    state["format"] = None
    state["waiting_for"] = None


def split_message(text, max_len=4000):
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks


# ─── MAIN ───

def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("help", ajuda))
    app.add_handler(CommandHandler("marca", cmd_marca))
    app.add_handler(CommandHandler("criar", cmd_criar))
    app.add_handler(CommandHandler("post", cmd_direto))
    app.add_handler(CommandHandler("carrossel", cmd_direto))
    app.add_handler(CommandHandler("reels", cmd_direto))

    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Catarina bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
