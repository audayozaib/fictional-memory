import os
import re
import asyncio

from dotenv import load_dotenv

from telethon import TelegramClient, events, types, utils
from telethon.sessions import StringSession


# ============================================================
# LOAD ENV
# ============================================================

load_dotenv()


def required_env(name):
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Missing environment variable: {name}"
        )

    return value.strip()


API_ID = int(required_env("API_ID"))
API_HASH = required_env("API_HASH")
SESSION_STRING = required_env("SESSION_STRING")


# ============================================================
# CHANNEL SETTINGS
#
# SOURCE_CHANNEL can be:
#   -1001234567890
#   @username
#   username
#   https://t.me/username
#
# TARGET_CHANNEL can use the same formats.
# ============================================================

SOURCE_CHANNEL = required_env("SOURCE_CHANNEL")
TARGET_CHANNEL = required_env("TARGET_CHANNEL")

TARGET_CHANNEL_LINK = required_env(
    "TARGET_CHANNEL_LINK"
)

TARGET_CHANNEL_USERNAME = required_env(
    "TARGET_CHANNEL_USERNAME"
)


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
)


# ============================================================
# REGEX
# ============================================================

URL_REGEX = re.compile(
    r"(?i)"
    r"(?:https?://|www\.)[^\s<>()]+"
    r"|(?:https?://)?(?:t\.me|telegram\.me)/[^\s<>()]+"
)

USERNAME_REGEX = re.compile(
    r"(?<![\w])@[A-Za-z0-9_]{3,32}\b"
)


# ============================================================
# CLEAN URL
# ============================================================

def clean_url(url):
    trailing = ""

    while url and url[-1] in (
        ".",
        ",",
        "!",
        "?",
        "،",
        "؛",
        ":",
        ")",
        "]",
        "}",
        ">",
        '"',
        "'",
    ):
        trailing = url[-1] + trailing
        url = url[:-1]

    return url, trailing


# ============================================================
# PLAIN TEXT LINK REPLACEMENT
# ============================================================

def replace_plain_links(text):

    if not text:
        return text

    # URLs
    def replace_url(match):

        original = match.group(0)

        url, trailing = clean_url(
            original
        )

        return (
            TARGET_CHANNEL_LINK
            + trailing
        )

    text = URL_REGEX.sub(
        replace_url,
        text
    )

    # @username
    text = USERNAME_REGEX.sub(
        lambda match: TARGET_CHANNEL_USERNAME,
        text
    )

    return text


# ============================================================
# ENTITY-AWARE TEXT TRANSFORMATION
#
# Handles hidden Telegram links.
#
# Example:
#
#   "اضغط هنا"
#
# where "اضغط هنا" secretly points to another URL.
#
# It becomes:
#
#   "https://t.me/MyChannel"
#
# ============================================================

def transform_text(text, entities):

    if not text:
        return "", []

    if not entities:
        return (
            replace_plain_links(text),
            []
        )

    source = utils.add_surrogate(text)

    replacements = []

    for entity in entities:

        # ----------------------------------------------------
        # Normal Telegram URL
        # ----------------------------------------------------

        if isinstance(
            entity,
            types.MessageEntityUrl
        ):

            start = entity.offset
            end = (
                start
                + entity.length
            )

            replacements.append(
                (
                    start,
                    end,
                    utils.add_surrogate(
                        TARGET_CHANNEL_LINK
                    ),
                )
            )

        # ----------------------------------------------------
        # Hidden URL
        # ----------------------------------------------------

        elif isinstance(
            entity,
            types.MessageEntityTextUrl
        ):

            start = entity.offset
            end = (
                start
                + entity.length
            )

            replacements.append(
                (
                    start,
                    end,
                    utils.add_surrogate(
                        TARGET_CHANNEL_LINK
                    ),
                )
            )

        # ----------------------------------------------------
        # @username mention
        # ----------------------------------------------------

        elif isinstance(
            entity,
            types.MessageEntityMention
        ):

            start = entity.offset
            end = (
                start
                + entity.length
            )

            replacements.append(
                (
                    start,
                    end,
                    utils.add_surrogate(
                        TARGET_CHANNEL_USERNAME
                    ),
                )
            )

    # No special entities
    if not replacements:

        return (
            replace_plain_links(text),
            entities
        )

    # Sort from beginning to end
    replacements.sort(
        key=lambda x: x[0]
    )

    # Build new text
    result = []

    cursor = 0

    for start, end, replacement in replacements:

        if start < cursor:
            continue

        result.append(
            source[cursor:start]
        )

        result.append(
            replacement
        )

        cursor = end

    result.append(
        source[cursor:]
    )

    new_source = "".join(result)

    new_text = utils.del_surrogate(
        new_source
    )

    # Run normal regex replacement too.
    new_text = replace_plain_links(
        new_text
    )

    # We intentionally return plain text
    # after URL/mention replacement.
    #
    # This prevents incorrect Telegram entity
    # offsets after changing URL lengths.
    return new_text, []


# ============================================================
# PROCESS MESSAGE TEXT / CAPTION
# ============================================================

def process_message_text(message):

    text = message.message or ""

    entities = message.entities or []

    return transform_text(
        text,
        entities
    )


# ============================================================
# RESOLVE CHANNEL
# ============================================================

async def resolve_channel(value, name):

    value = value.strip()

    print(
        f"[RESOLVE] {name}: {value}"
    )

    # --------------------------------------------------------
    # Numeric channel ID
    # --------------------------------------------------------

    try:

        channel_id = int(value)

        entity = await client.get_entity(
            channel_id
        )

        print(
            f"[RESOLVED] {name}: "
            f"{getattr(entity, 'title', channel_id)}"
        )

        return entity

    except ValueError:
        pass

    except Exception as e:

        print(
            f"[WARNING] Could not resolve "
            f"{name} as numeric ID: {e}"
        )

    # --------------------------------------------------------
    # Username / URL
    # --------------------------------------------------------

    username = value

    if username.startswith(
        "https://t.me/"
    ):
        username = username[
            len("https://t.me/"):
        ]

    elif username.startswith(
        "http://t.me/"
    ):
        username = username[
            len("http://t.me/"):
        ]

    elif username.startswith(
        "https://telegram.me/"
    ):
        username = username[
            len("https://telegram.me/"):
        ]

    elif username.startswith(
        "http://telegram.me/"
    ):
        username = username[
            len("http://telegram.me/"):
        ]

    elif username.startswith(
        "t.me/"
    ):
        username = username[
            len("t.me/"):
        ]

    elif username.startswith(
        "telegram.me/"
    ):
        username = username[
            len("telegram.me/"):
        ]

    username = username.strip()

    if not username.startswith("@"):
        username = "@" + username

    try:

        entity = await client.get_entity(
            username
        )

        print(
            f"[RESOLVED] {name}: "
            f"{getattr(entity, 'title', username)}"
        )

        return entity

    except Exception as e:

        raise RuntimeError(
            f"""
Could not resolve {name}: {value}

If this is a private channel:
1. Make sure the Telegram account is a member.
2. Open the channel using that account.
3. Make sure the SESSION_STRING belongs to that account.
4. For private channels, use the numeric -100... ID.

Original error:
{e}
"""
        )


# ============================================================
# SEND SINGLE MESSAGE
# ============================================================

async def send_single_message(
    message,
    target_entity
):

    text, entities = process_message_text(
        message
    )

    # --------------------------------------------------------
    # Text only
    # --------------------------------------------------------

    if not message.media:

        if not text:
            return

        await client.send_message(
            target_entity,
            text,
            formatting_entities=(
                entities
                if entities
                else None
            ),
            link_preview=False,
        )

        return

    # --------------------------------------------------------
    # Media + caption
    #
    # This sends the media and caption together.
    # --------------------------------------------------------

    await client.send_file(
        target_entity,
        message.media,
        caption=(
            text
            if text
            else None
        ),
        formatting_entities=(
            entities
            if entities
            else None
        ),
    )


# ============================================================
# ALBUM MANAGEMENT
# ============================================================

album_tasks = {}


async def collect_album(
    grouped_id,
    first_message,
    target_entity
):

    try:

        # ----------------------------------------------------
        # Give Telegram a moment to deliver the complete group.
        # ----------------------------------------------------

        await asyncio.sleep(1.0)

        # ----------------------------------------------------
        # Get messages around the first album message.
        #
        # Usually albums contain only a handful of messages.
        # ----------------------------------------------------

        messages = await client.get_messages(
            SOURCE_CHANNEL,
            limit=100,
            min_id=max(
                0,
                first_message.id - 20
            ),
            max_id=(
                first_message.id + 20
            ),
        )

        album = [
            message
            for message in messages
            if (
                message.grouped_id
                == grouped_id
            )
        ]

        # ----------------------------------------------------
        # If the local search did not find the album,
        # use the first message itself.
        # ----------------------------------------------------

        if not album:

            album = [
                first_message
            ]

        # Original Telegram order
        album.sort(
            key=lambda message: message.id
        )

        files = []

        caption = None
        entities = []

        for message in album:

            if message.media:

                files.append(
                    message.media
                )

            # Telegram normally puts the caption
            # on the first album item.
            if (
                message.message
                and caption is None
            ):

                caption, entities = (
                    process_message_text(
                        message
                    )
                )

        if not files:
            return

        # ----------------------------------------------------
        # Send entire album together.
        #
        # This is important:
        #
        # 5 photos in source
        #       ↓
        # 1 Telegram media group in target
        #
        # not 5 separate posts.
        # ----------------------------------------------------

        await client.send_file(
            target_entity,
            files,
            caption=(
                caption
                if caption
                else None
            ),
            formatting_entities=(
                entities
                if entities
                else None
            ),
        )

        print(
            f"[ALBUM DONE] "
            f"grouped_id={grouped_id} "
            f"items={len(files)}"
        )

    except Exception as e:

        print(
            f"[ALBUM ERROR] "
            f"{grouped_id}: {e}"
        )

    finally:

        album_tasks.pop(
            grouped_id,
            None
        )


# ============================================================
# NEW MESSAGE HANDLER
# ============================================================

@client.on(
    events.NewMessage(
        chats=SOURCE_CHANNEL
    )
)
async def new_message_handler(event):

    message = event.message

    print(
        f"[NEW] "
        f"id={message.id} "
        f"grouped={message.grouped_id}"
    )

    # --------------------------------------------------------
    # Media Group / Album
    # --------------------------------------------------------

    if message.grouped_id:

        grouped_id = message.grouped_id

        if grouped_id not in album_tasks:

            task = asyncio.create_task(
                collect_album(
                    grouped_id,
                    message,
                    TARGET_ENTITY,
                )
            )

            album_tasks[
                grouped_id
            ] = task

        return

    # --------------------------------------------------------
    # Normal message
    # --------------------------------------------------------

    try:

        await send_single_message(
            message,
            TARGET_ENTITY,
        )

        print(
            f"[DONE] "
            f"id={message.id}"
        )

    except Exception as e:

        print(
            f"[ERROR] "
            f"id={message.id}: {e}"
        )


# ============================================================
# MAIN
# ============================================================

TARGET_ENTITY = None


async def main():

    global TARGET_ENTITY

    print("=" * 60)
    print(
        "Telegram Channel Copy Userbot"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # Login
    # --------------------------------------------------------

    await client.start()

    me = await client.get_me()

    print(
        f"[LOGIN] "
        f"{me.first_name or ''} "
        f"{me.username or ''}"
    )

    # --------------------------------------------------------
    # Resolve source
    # --------------------------------------------------------

    source_entity = await resolve_channel(
        SOURCE_CHANNEL,
        "SOURCE_CHANNEL"
    )

    # --------------------------------------------------------
    # Resolve target
    # --------------------------------------------------------

    TARGET_ENTITY = await resolve_channel(
        TARGET_CHANNEL,
        "TARGET_CHANNEL"
    )

    print("=" * 60)

    print(
        "[SOURCE] "
        f"{getattr(source_entity, 'title', 'Unknown')}"
    )

    print(
        "[TARGET] "
        f"{getattr(TARGET_ENTITY, 'title', 'Unknown')}"
    )

    print("=" * 60)

    print(
        "[STATUS] Userbot is running..."
    )

    print(
        "[STATUS] Waiting for new messages..."
    )

    # --------------------------------------------------------
    # Run forever
    # --------------------------------------------------------

    await client.run_until_disconnected()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n[STOPPED] Userbot stopped."
        )

    except Exception as e:

        print(
            "\n[FATAL ERROR]"
        )

        print(e)