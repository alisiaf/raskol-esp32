from machine import Pin, SPI
from time import sleep_ms
import mfrc522

SCK = 18
MOSI = 23
MISO = 4
CS = 22
RST = 21

spi = SPI(2, sck=Pin(SCK), mosi=Pin(MOSI), miso=Pin(MISO))
rdr = mfrc522.MFRC522(spi=spi, gpioRst=Pin(RST), gpioCs=Pin(CS))

print("Тест чтения блоков. Ожидание метки...")

while True:
    (stat, tag_type) = rdr.request(rdr.REQIDL)
    if stat == rdr.OK:
        (stat, raw_uid) = rdr.anticoll()
        if stat == rdr.OK:
            print("UID:", '-'.join('{:02X}'.format(b) for b in raw_uid))
            
            # Пробуем читать блоки 4 и 5 напрямую, без select_tag и auth
            block4 = bytearray(16)
            block5 = bytearray(16)
            
            # Метод read сам отправляет команду, если карта уже активна
            if rdr.read(4, into=block4):
                print("Block 4:", block4)
            else:
                print("Block 4: FAIL")
                
            if rdr.read(5, into=block5):
                print("Block 5:", block5)
            else:
                print("Block 5: FAIL")
                
            sleep_ms(1000)   # пауза, чтобы не спамить