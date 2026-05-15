import asyncio
import sys
import os
import argparse
import random
from datetime import datetime
from nats.aio.client import Client as NATS
from openai import AsyncOpenAI
from dotenv import load_dotenv

ROOM = "room.general"
PASS_TOKEN = "---pass---"


def strip_name(text, name):
    for prefix in (f"{name}:", f"{name.lower()}:", f"{name.capitalize()}:"):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


_REASONING_PATTERNS = (
    "we need to", "first,", "let me", "i need to", "i think", "i will",
    "forse", "devo", "penso che", "dovrei", "puoi", "possiamo",
    "the user says", "the user's", "our persona", "we are",
    "key points:", "draft", "proposed", "option", "alternativa",
)


def is_reasoning(text):
    lower = text.lower()
    for p in _REASONING_PATTERNS:
        if lower.startswith(p) or f" {p}" in lower[:200]:
            return True
    return len(text) > 300


def extract_message(text):
    last_quote = None
    for q in ('"', "'", '"', "'"):
        idx = text.rfind(q)
        if idx > len(text) // 2:
            candidate = text[idx+1:]
            end = candidate.find(q)
            if end > 0 and len(candidate[:end]) > 5:
                last_quote = candidate[:end]
    if last_quote:
        return last_quote

    for sep in ("Scrivo:", "scrivo:", "Risposta:", "risposta:",
                "Message:", "message:", "Output:", "output:"):
        idx = text.rfind(sep)
        if idx > len(text) // 2:
            return text[idx + len(sep):].strip()

    return text


async def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Agente LLM per stanza NATS")
    parser.add_argument("--name", required=True, help="Nome dell'agente")
    parser.add_argument("--prompt", required=True, help="Prompt di personalita")
    parser.add_argument("--model", default=(
        os.getenv("OPENCODE_MODEL") or os.getenv("OPENAI_MODEL")
        or "deepseek-v4-flash"))
    parser.add_argument("--api-key", default=(
        os.getenv("OPENCODE_API_KEY")
        or os.getenv("OPENAI_API_KEY")))
    parser.add_argument("--base-url", default=(
        os.getenv("OPENCODE_API_URL", "")
        .removesuffix("/chat/completions")
        .removesuffix("/")
        or os.getenv("OPENAI_BASE_URL")
        or "https://opencode.ai/zen/go/v1"))
    parser.add_argument("--max-tokens", type=int, default=2048,
                        help="Max token per risposta LLM")
    parser.add_argument("--nats-url", default="nats://127.0.0.1:4222")
    args = parser.parse_args()

    if not args.api_key:
        print("ERRORE: serve --api-key o OPENAI_API_KEY")
        sys.exit(1)

    client = AsyncOpenAI(api_key=args.api_key, base_url=args.base_url)
    nc = NATS()
    await nc.connect(args.nats_url)

    history = []
    msg_queue = asyncio.Queue()

    async def handler(msg):
        await msg_queue.put(msg)

    await nc.subscribe(ROOM, cb=handler)
    print(f"[{args.name}] Connesso. Genero messaggio di apertura...")

    first_messages = [
        {
            "role": "system",
            "content": (
                f"Sei {args.name}. {args.prompt}\n\n"
                "Sei appena entrato in una chat room con altri agenti AI.\n"
                "Non c'e' ancora nessun messaggio. Devi fare tu il primo passo.\n\n"
                "REGOLE:\n"
                "1. Scrivi SOLO il messaggio di apertura. Niente pensieri, niente ragionamenti.\n"
                "2. Massimo 2-3 frasi.\n"
                "3. Non usare prefissi o markup."
            ),
        },
    ]

    try:
        sys.stdout.write("[pensando...] ")
        sys.stdout.flush()
        response = await client.chat.completions.create(
            model=args.model,
            messages=first_messages,
            temperature=0.9,
            max_tokens=args.max_tokens,
        )
        msg = response.choices[0].message
        opening = (msg.content or getattr(msg, "reasoning_content", "") or "").strip()
        opening = extract_message(opening) if not msg.content else opening
        opening = strip_name(opening, args.name)
        if not opening:
            opening = "Salve a tutti!"
    except Exception as e:
        print(f"\n[{args.name}] ERRORE generazione apertura: {e}")
        opening = "Salve a tutti!"

    payload = f"{args.name}: {opening}"
    history.append({"role": "assistant", "content": payload})
    await nc.publish(ROOM, payload.encode())
    print(f"[{args.name}] {opening}")
    print(f"[{args.name}] In ascolto su {ROOM}")

    while True:
        msg = await msg_queue.get()
        text = msg.data.decode()

        if ": " not in text:
            continue

        sender, content = text.split(": ", 1)

        if sender == args.name:
            continue

        now = datetime.now().isoformat()

        history.append({"role": "user", "content": f"{sender}: {content}"})
        history = history[-40:]

        sys.stdout.write(f"\n[{now}] {sender}: {content}\n")
        sys.stdout.write("> ")
        sys.stdout.flush()

        await asyncio.sleep(random.uniform(0.5, 2.0))

        messages = [
            {
                "role": "system",
                "content": (
                    f"Sei {args.name}. {args.prompt}\n\n"
                    "Sei in una chat room con altri agenti AI.\n"
                    "Leggi la cronologia della conversazione.\n\n"
                    "REGOLE:\n"
                    f"1. Se VUOI rispondere, scrivi SOLO il tuo messaggio. "
                    "Niente pensieri, niente ragionamenti, niente analisi.\n"
                    f"2. Se NON vuoi rispondere, scrivi solo '{PASS_TOKEN}'.\n"
                    "3. Non ripeterti.\n"
                    "4. Sii conciso (max 2-3 frasi).\n"
                    "5. Riferisciti agli altri agenti per nome.\n"
                    "6. Non dire cosa stai per fare. Non analizzare la situazione. "
                    "Scrivi direttamente il messaggio come in una chat."
                ),
            },
            *history,
        ]

        try:
            sys.stdout.write("\n[pensando...] ")
            sys.stdout.flush()
            response = await client.chat.completions.create(
                model=args.model,
                messages=messages,
                temperature=0.9,
                max_tokens=args.max_tokens,
            )
            msg = response.choices[0].message
            reply = (msg.content or getattr(msg, "reasoning_content", "") or "").strip()
            if not msg.content:
                reply = extract_message(reply)
            elif is_reasoning(reply):
                extracted = extract_message(reply)
                if extracted != reply:
                    reply = extracted
            reply = strip_name(reply, args.name)

            if reply and reply != PASS_TOKEN and len(reply) > 10 and not is_reasoning(reply):
                payload = f"{args.name}: {reply}"
                history.append({"role": "assistant", "content": payload})
                await nc.publish(ROOM, payload.encode())
                sys.stdout.write(f"[{now}] {args.name}: {reply}\n")
                sys.stdout.write("> ")
                sys.stdout.flush()

        except Exception as e:
            sys.stdout.write(f"[{args.name}] ERRORE: {e}\n")
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgente fermato.")
