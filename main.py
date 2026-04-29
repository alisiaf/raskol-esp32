import mfrc522     # https://github.com/cefn/micropython-mfrc522
from machine import Pin, SPI
from time import sleep_ms
cs = Pin(5, Pin.OUT)
rst = Pin(4, Pin.OUT)
led= Pin(2, Pin.OUT)
vspi = SPI(2)
rdr = mfrc522.MFRC522(spi=vspi, gpioRst=rst, gpioCs=cs)
led.on()
print('Приложите метку')

def get_exact_text(chunks):
    full_data = bytearray()
    for c in chunks:
        full_data.extend(c)
    
    try:
        # 1. Ищем заголовок текстовой записи (стандарт: 0x54 или 'T')
        if b'T' not in full_data:
            return "Пустая метка"
            
        t_idx = full_data.index(b'T')
        
        # 2. Длина всей полезной нагрузки (Payload) указана ПЕРЕД байтом 'T'
        # В вашем массиве это байт 0x07 (перед 'T')
        payload_len = full_data[t_idx - 1]
        
        # 3. Определяем длину кода языка (байт после 'T')
        status_byte = full_data[t_idx + 1]
        lang_len = status_byte & 0x3F
        
        # 4. Текст начинается после: T(1) + Status(1) + Lang(lang_len)
        text_start = t_idx + 2 + lang_len
        
        # 5. Длина ЧИСТОГО текста = Общая длина нагрузки - (Status + Lang)
        pure_text_len = payload_len - (1 + lang_len)
        
        # Извлекаем ровно столько байт, сколько указано в заголовке
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
            #print('type: 0x%02X' % tag_type)
            #print('uid: %02X-%02X-%02X-%02X-%02X' % ( raw_uid[0], raw_uid[1], raw_uid[2], raw_uid[3], raw_uid[4]))
            #print('')
            if rdr.select_tag(raw_uid) == rdr.OK:
                #key = b'\xff\xff\xff\xff\xff\xff'
                blockArray = bytearray(16)
                for sector in range(0, 6):
                    rdr.read(sector, into=blockArray)
                    #print("Blok dat c.%d: " % sector, end="")
                    #print('-'.join(f'{b:02x}' for b in blockArray))
                    #print(blockArray)
                    if sector==4:
                        blockArray0=blockArray
                    if  sector==5:
                        print(get_exact_text([blockArray0,blockArray]))
                rdr.stop_crypto1()
            else:
                print("Ошибка выбора")
            sleep_ms(100)
            led.on()
            print("Приложите метку")
            
