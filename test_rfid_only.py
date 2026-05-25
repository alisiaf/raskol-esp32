from machine import Pin, SPI
from time import sleep_ms
import mfrc522

# ---------- АКТУАЛЬНЫЕ ПИНЫ RFID ----------
RFID_SCK  = 2
RFID_MOSI = 33
RFID_MISO = 19
RFID_CS   = 5
RFID_RST  = 21

READ_BLOCKS = (4, 5, 6, 8)
KNOWN_COLORS = (
    "white",
    "black",
    "red",
    "yellow",
    "blue",
    "green",
    "orange",
    "pink",
    "purple",
    "brown",
    "grey",
)


def bytes_to_safe_ascii(data):
    chars = []
    for b in data:
        if 32 <= b <= 126:
            chars.append(chr(b))
        else:
            chars.append(" ")
    return "".join(chars)

def make_utf16le_pattern(text):
    pattern = bytearray()
    for ch in text:
        pattern.append(ord(ch))
        pattern.append(0)
    return bytes(pattern)

def extract_color_fallback(chunks):
    merged = bytearray()
    for chunk in chunks:
        merged.extend(chunk)

    merged_bytes = bytes(merged)
    for color in KNOWN_COLORS:
        if color.encode() in merged_bytes:
            return color
        if make_utf16le_pattern(color) in merged_bytes:
            return color

    safe_text = bytes_to_safe_ascii(merged).lower()
    for color in KNOWN_COLORS:
        if color in safe_text:
            return color
    return ""

def decode_ndef_text(data):
    try:
        if b"T" not in data:
            return ""

        t_idx = data.index(b"T")
        payload_len = data[t_idx - 1]
        status_byte = data[t_idx + 1]
        lang_len = status_byte & 0x3F
        text_start = t_idx + 2 + lang_len
        pure_text_len = payload_len - (1 + lang_len)
        text_bytes = data[text_start:text_start + pure_text_len]

        decoded = bytes_to_safe_ascii(text_bytes).strip().lower()
        if decoded in KNOWN_COLORS:
            return decoded
        return ""
    except Exception:
        return ""

def get_exact_text(chunks):
    merged = bytearray()
    for chunk in chunks:
        merged.extend(chunk)

    text = extract_color_fallback(chunks)
    if text:
        return text

    text = decode_ndef_text(merged)
    if text:
        return text

    for chunk in chunks:
        text = decode_ndef_text(chunk)
        if text:
            return text

    return ""


spi = SPI(
    2,
    sck=Pin(RFID_SCK),
    mosi=Pin(RFID_MOSI),
    miso=Pin(RFID_MISO),
)
rdr = mfrc522.MFRC522(
    spi=spi,
    gpioRst=Pin(RFID_RST, Pin.OUT),
    gpioCs=Pin(RFID_CS, Pin.OUT),
)

print("RFID test started")
print("Pins: SCK={}, MOSI={}, MISO={}, CS={}, RST={}".format(
    RFID_SCK, RFID_MOSI, RFID_MISO, RFID_CS, RFID_RST
))
print("Bring tag to 0-2 cm")

while True:
    stat, tag_type = rdr.request(rdr.REQIDL)
    if stat != rdr.OK:
        sleep_ms(100)
        continue

    print("\nTag detected, type:", hex(tag_type))

    stat, raw_uid = rdr.anticoll()
    if stat != rdr.OK:
        print("Anticoll FAIL")
        sleep_ms(500)
        continue

    print("UID:", "-".join("{:02X}".format(b) for b in raw_uid))

    if rdr.select_tag(raw_uid) != rdr.OK:
        print("Select tag FAIL")
        sleep_ms(500)
        continue

    blocks = []
    for block_num in READ_BLOCKS:
        block = bytearray(16)
        ok = rdr.read(block_num, into=block) is not None
        blocks.append((block_num, ok, block))
    rdr.stop_crypto1()

    for block_num, ok, block in blocks:
        if ok:
            print("Block {}:".format(block_num), block)
        else:
            print("Block {}: FAIL".format(block_num))

    chunk_list = [block for _, ok, block in blocks if ok]
    if chunk_list:
        text = get_exact_text(chunk_list)
        if text:
            print("Decoded text:", text)
        else:
            print("Decoded text: not found")

        merged = bytearray()
        for chunk in chunk_list:
            merged.extend(chunk)
        raw_text = bytes_to_safe_ascii(merged)
        print("Raw ascii view:", raw_text)

    print("Remove/reapply tag for next read")
    sleep_ms(1000)
