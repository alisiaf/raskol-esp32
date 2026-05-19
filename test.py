import mfrc522
from machine import Pin, SPI
from time import sleep_ms

# ВАШИ пины (по схеме, которую мы использовали)
cs = Pin(22, Pin.OUT)   # SDA/CS
rst = Pin(21, Pin.OUT)  # RST
led = Pin(2, Pin.OUT)

vspi = SPI(2)   # используем тот же SPI2, что и в основном коде
rdr = mfrc522.MFRC522(spi=vspi, gpioRst=rst, gpioCs=cs)
led.on()
print('Приложите метку')

def get_exact_text(chunks):
    full_data = bytearray()
    for c in chunks:
        full_data.extend(c)
    try:
        if b'T' not in full_data:
            return "Пустая метка"
        t_idx = full_data.index(b'T')
        payload_len = full_data[t_idx - 1]
        status_byte = full_data[t_idx + 1]
        lang_len = status_byte & 0x3F
        text_start = t_idx + 2 + lang_len
        pure_text_len = payload_len - (1 + lang_len)
        text_bytes = full_data[text_start : text_start + pure_text_len]
        return text_bytes.decode('utf-8')
    except Exception as e:
        return f"Ошибка: {e}"

while True:
    (stat, tag_type) = rdr.request(rdr.REQIDL)
    if stat == rdr.OK:
        (stat, raw_uid) = rdr.anticoll()
        led.off()
        if stat == rdr.OK:
            if rdr.select_tag(raw_uid) == rdr.OK:
                blockArray = bytearray(16)
                for sector in range(0, 6):
                    rdr.read(sector, into=blockArray)
                    print("Blok dat c.%d: " % sector, end="")
                    print('-'.join(f'{b:02x}' for b in blockArray))
                    print(blockArray)
                    if sector==4:
                        blockArray0=blockArray
                    if sector==5:
                        print(get_exact_text([blockArray0,blockArray]))
                rdr.stop_crypto1()
            else:
                print("Ошибка выбора")
            sleep_ms(100)
            led.on()
            print("Приложите метку")
