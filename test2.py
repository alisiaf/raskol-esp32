from machine import Pin, SPI
from time import sleep_ms
import mfrc522

# Твои пины
SCK = 18
MOSI = 23
MISO = 19
CS = 22
RST = 21

spi = SPI(2, sck=Pin(SCK), mosi=Pin(MOSI), miso=Pin(MISO))
rdr = mfrc522.MFRC522(spi=spi, gpioRst=Pin(RST), gpioCs=Pin(CS))

print("RFID test started. Ожидание метки...")

while True:
    (stat, tag_type) = rdr.request(rdr.REQIDL)
    if stat == rdr.OK:
        print("Request OK, type:", hex(tag_type))
        (stat, raw_uid) = rdr.anticoll()
        if stat == rdr.OK:
            print("UID:", '-'.join('{:02X}'.format(b) for b in raw_uid))
            if rdr.select_tag(raw_uid) == rdr.OK:
                print("Select OK. Читаю блоки 4 и 5...")
                block4 = bytearray(16)
                block5 = bytearray(16)
                stat4 = rdr.read(4, into=block4)
                stat5 = rdr.read(5, into=block5)
                print("Block 4 read:", "OK" if stat4 else "FAIL", block4)
                print("Block 5 read:", "OK" if stat5 else "FAIL", block5)
                rdr.stop_crypto1()
            else:
                print("Select FAIL")
        else:
            print("Anticoll FAIL")
        sleep_ms(500)
    else:
        # Если stat не OK, просто ждем, не спамим
        pass