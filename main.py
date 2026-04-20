from machine import I2C, Pin, PWM
from micropython import const
import bluetooth
import time
import uasyncio as asio

from BLEUART import BLEUART
from MX1508 import MX1508

try:
    from tcs34725 import TCS34725, rgb_to_hsv
except ImportError:
    TCS34725 = None
    rgb_to_hsv = None


LEFT_MOTOR_IN1 = 25
LEFT_MOTOR_IN2 = 26
RIGHT_MOTOR_IN1 = 27
RIGHT_MOTOR_IN2 = 14

GRIP_SERVO_PIN = 13
BUCKET_SERVO_PIN = 33

I2C_SDA_PIN = 17
I2C_SCL_PIN = 16

BLE_NAME = "RASKOL_BOT"

DRIVE_SPEED = 900
TURN_SPEED = 900

GRIP_OPEN_ANGLE = 110
GRIP_CLOSED_ANGLE = 55

BUCKET_MIN_ANGLE = 20
BUCKET_MAX_ANGLE = 160
BUCKET_START_ANGLE = 90
BUCKET_STEP = 10

SERVO_FREQ = 50
SERVO_MIN_DUTY = 20
SERVO_MAX_DUTY = 120

LOOP_DELAY_MS = const(20)
LED_PULSE_MS = const(150)


comand = ""
on = 0
bucket_angle = BUCKET_START_ANGLE
led_pulse_started = 0


led = Pin(2, Pin.OUT)
led.value(0)

left_motor = MX1508(LEFT_MOTOR_IN1, LEFT_MOTOR_IN2)
right_motor = MX1508(RIGHT_MOTOR_IN1, RIGHT_MOTOR_IN2)

grip_pwm = PWM(Pin(GRIP_SERVO_PIN, Pin.OUT))
grip_pwm.freq(SERVO_FREQ)

bucket_pwm = PWM(Pin(BUCKET_SERVO_PIN, Pin.OUT))
bucket_pwm.freq(SERVO_FREQ)

sensor = None


def clamp(value, low, high):
    return min(high, max(low, value))


def map_value(x, in_min, in_max, out_min, out_max):
    return int((x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min)


def servo_write(pwm_pin, angle):
    angle = clamp(int(angle), 0, 180)
    duty = map_value(angle, 0, 180, SERVO_MIN_DUTY, SERVO_MAX_DUTY)
    pwm_pin.duty(duty)


def pulse_led():
    global led_pulse_started
    led_pulse_started = time.ticks_ms()
    led.value(1)


def update_led():
    if led.value() == 0:
        return

    now = time.ticks_ms()
    if time.ticks_diff(now, led_pulse_started) > LED_PULSE_MS:
        led.value(0)


def send_status(message):
    try:
        uart.write((message + "\r\n").encode())
    except Exception:
        pass


def normalize_command(raw_command):
    command = raw_command.strip().upper()
    if not command:
        return ""

    if command.startswith("!B") and len(command) > 2:
        command = command[2:]

    return command


def on_rx():
    global comand, on

    on = 1
    try:
        raw_data = uart.read()
        if not raw_data:
            return

        text = raw_data.decode()
        for line in text.replace("\r", "\n").split("\n"):
            normalized = normalize_command(line)
            if normalized:
                comand = normalized
                print("Получена команда:", comand)
    except Exception as e:
        print("Ошибка декодирования:", e)


def motors_stop():
    left_motor.stop()
    right_motor.stop()


def motors_forward(speed=DRIVE_SPEED):
    left_motor.forward(speed)
    right_motor.forward(speed)


def motors_backward(speed=DRIVE_SPEED):
    left_motor.reverse(speed)
    right_motor.reverse(speed)


def motors_left(speed=TURN_SPEED):
    left_motor.reverse(speed)
    right_motor.forward(speed)


def motors_right(speed=TURN_SPEED):
    left_motor.forward(speed)
    right_motor.reverse(speed)


def init_color_sensor():
    if TCS34725 is None:
        return None

    try:
        i2c_bus = I2C(0, sda=Pin(I2C_SDA_PIN), scl=Pin(I2C_SCL_PIN))
        color_sensor = TCS34725(i2c_bus)
        color_sensor.gain(4)
        color_sensor.integration_time(80)
        return color_sensor
    except Exception as e:
        print("Датчик цвета не найден:", e)
        return None


def classify_color(raw_rgb):
    if rgb_to_hsv is None:
        return "sensor_off"

    r, g, b = raw_rgb[0], raw_rgb[1], raw_rgb[2]
    h, s, v = rgb_to_hsv(r, g, b)

    if h > 340 or h < 10:
        return "red"
    if 10 < h < 60:
        return "orange"
    if 60 < h < 120:
        return "yellow"
    if 120 < h < 180:
        return "green"
    if 180 < h < 240:
        if v > 50:
            return "blue"
        return "black"
    return "unknown"


def read_cube_mark():
    if sensor is None:
        return "sensor_not_found"

    try:
        raw_rgb = sensor.read(True)
        return classify_color(raw_rgb)
    except Exception as e:
        print("Ошибка чтения метки:", e)
        return "read_error"


def grab_and_scan():
    servo_write(grip_pwm, GRIP_CLOSED_ANGLE)
    time.sleep_ms(300)
    mark = read_cube_mark()
    print("Захват выполнен, метка:", mark)
    send_status("grabbed;mark={}".format(mark))


def release_cube():
    servo_write(grip_pwm, GRIP_OPEN_ANGLE)
    print("Захват открыт")
    send_status("released")


def bucket_up():
    global bucket_angle

    bucket_angle = clamp(bucket_angle + BUCKET_STEP, BUCKET_MIN_ANGLE, BUCKET_MAX_ANGLE)
    servo_write(bucket_pwm, bucket_angle)
    print("Ковш вверх, угол:", bucket_angle)
    send_status("bucket={}".format(bucket_angle))


def bucket_down():
    global bucket_angle

    bucket_angle = clamp(bucket_angle - BUCKET_STEP, BUCKET_MIN_ANGLE, BUCKET_MAX_ANGLE)
    servo_write(bucket_pwm, bucket_angle)
    print("Ковш вниз, угол:", bucket_angle)
    send_status("bucket={}".format(bucket_angle))


ble = bluetooth.BLE()
uart = BLEUART(ble, name=BLE_NAME)
uart.irq(handler=on_rx)


sensor = init_color_sensor()
motors_stop()
servo_write(grip_pwm, GRIP_OPEN_ANGLE)
servo_write(bucket_pwm, bucket_angle)

print("ESP32 BLE UART готов")
print("Имя BLE:", BLE_NAME)
print("Движение: 516-вперед, 615-назад, 414-влево, 315-вправо, 507/606-стоп")
print("Bluefruit 4 кнопки: 1-захват+метка, 2-разжать, 3-ковш вверх, 4-ковш вниз")
send_status("ready")


async def do_it(int_ms):
    global comand, on

    while True:
        await asio.sleep_ms(int_ms)

        if comand == "516":
            print("Команда 516: вперед")
            motors_forward()
            pulse_led()
            send_status("move=forward")
            comand = ""

        elif comand == "615":
            print("Команда 615: назад")
            motors_backward()
            pulse_led()
            send_status("move=backward")
            comand = ""

        elif comand == "414":
            print("Команда 414: разворот влево")
            motors_left()
            pulse_led()
            send_status("move=left")
            comand = ""

        elif comand == "315":
            print("Команда 315: разворот вправо")
            motors_right()
            pulse_led()
            send_status("move=right")
            comand = ""

        elif comand == "507" or comand == "606" or comand == "STOP":
            print("Команда стоп")
            motors_stop()
            pulse_led()
            send_status("move=stop")
            comand = ""

        elif comand == "1" or comand == "BTN1" or comand == "B1":
            print("Кнопка 1: захват и чтение метки")
            pulse_led()
            grab_and_scan()
            comand = ""

        elif comand == "2" or comand == "BTN2" or comand == "B2":
            print("Кнопка 2: разжатие")
            pulse_led()
            release_cube()
            comand = ""

        elif comand == "3" or comand == "BTN3" or comand == "B3":
            print("Кнопка 3: ковш вверх")
            pulse_led()
            bucket_up()
            comand = ""

        elif comand == "4" or comand == "BTN4" or comand == "B4":
            print("Кнопка 4: ковш вниз")
            pulse_led()
            bucket_down()
            comand = ""

        update_led()


loop = asio.get_event_loop()
loop.create_task(do_it(LOOP_DELAY_MS))

try:
    loop.run_forever()
except Exception:
    motors_stop()
    uart.close()
