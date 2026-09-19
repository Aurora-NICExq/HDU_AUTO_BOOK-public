import requests
import yaml
import random
from datetime import datetime, timedelta
import json
import os
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
import time


logging.basicConfig(
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
BOOK_DAYS_AHEAD = 2  # 预约后天
ALREADY_BOOKED_KEYS = ("已有预约", "重复预约", "请先取消", "当前已有", "只能预约一个", "已存在预约")
SEAT_TAKEN_KEYS = ("已被", "占用", "不可用", "不存在", "冲突")


def target_weekday_name():
    return WEEKDAYS[(datetime.now().weekday() + BOOK_DAYS_AHEAD) % 7]


def expand_seat_cfg(cfg):
    if not cfg:
        return []
    if cfg.get('ranges'):
        ids = []
        for pair in cfg['ranges']:
            ids.extend(range(pair[0], pair[1] + 1))
        return ids
    if 'begin' in cfg and 'end' in cfg:
        return list(range(cfg['begin'], cfg['end'] + 1))
    return []


def get_seats_with_config(user_config, date_config, seat_config):
    seat_name = date_config['name']
    if seat_name == "自定义":
        return user_config['自定义']
    return expand_seat_cfg(seat_config[seat_name])


def _json_has_booking(obj, depth=0):
    if depth > 12 or obj is None:
        return False
    if isinstance(obj, dict):
        for key in ("bookingId", "booking_id", "appointId", "appointment_id"):
            val = obj.get(key)
            if val not in (None, "", 0, "0"):
                return True
        ui = str(obj.get("ui_type") or "")
        if "BookingItem" in ui or "MyBooking" in ui:
            if obj.get("seatNum") or obj.get("roomName") or obj.get("id"):
                return True
        return any(_json_has_booking(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return any(_json_has_booking(v, depth + 1) for v in obj)
    return False


class SeatAutoBooker:
    def __init__(self, booker_config):
        self.json = None
        self.resp = None
        self.user_data = None

        logging.info('Creating SeatAutoBooker object')

        self.un = os.environ["SCHOOL_ID"].strip()  # 学号
        print("使用用户：{}".format(self.un))
        self.pd = os.environ["PASSWORD"].strip()  # 密码
        self.SCKey = None
        try:
            self.SCKey = os.environ["SCKEY"]
        except KeyError:
            print("没有Server酱的key,将不会推送消息")

        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        # chromedriver 路径：环境变量 CHROMEDRIVER_PATH 可覆盖，其次探测常见安装位置，最后交给 PATH 解析
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "")
        if not chromedriver_path:
            for candidate in ('/usr/local/bin/chromedriver', '/opt/homebrew/bin/chromedriver'):
                if os.path.exists(candidate):
                    chromedriver_path = candidate
                    break
        service = Service(chromedriver_path) if chromedriver_path else Service()
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10, 0.5)
        self.cookie = None

        self.cfg = booker_config

    def book_favorite_seat(self, user_config, seat_config):
        retry_sleep_time = timedelta(minutes=self.cfg["cron-delta-minutes"]).seconds*2/(self.cfg["max-retry"]-2) - 10
        for tried_times in range(self.cfg["max-retry"]):
            try:
                result = self._book_favorite_seat(user_config, seat_config, tried_times)
                msg = str(result[1]) if result else ""
                if result and any(k in msg for k in ALREADY_BOOKED_KEYS):
                    print("已有预约，结束：{}".format(result[1]))
                    return result
                if result and any(k in msg for k in ("频繁", "人数过多")):
                    print("触发限流({})，{:.0f}秒后重试".format(result[1], retry_sleep_time))
                    time.sleep(retry_sleep_time)
                    continue
                if result and any(k in msg for k in SEAT_TAKEN_KEYS):
                    print("座位不可约({})，换一个再试".format(result[1]))
                    continue
                return result
            except Exception as e:
                logging.exception(e)
                print(e.__class__, "尝试第{}次".format(tried_times))
                time.sleep(retry_sleep_time)

    def _book_favorite_seat(self, user_config, seat_config, tried_times=0):
        logging.info('Entering _book_favorite_seat method')
        date_config = user_config[target_weekday_name()]
        seats = get_seats_with_config(user_config, date_config, seat_config)
        today_0_clock = datetime.strptime(datetime.now().strftime("%Y-%m-%d 00:00:00"), "%Y-%m-%d %H:%M:%S")
        book_time = today_0_clock + timedelta(days=BOOK_DAYS_AHEAD) + timedelta(hours=date_config['开始时间'])
        delta = book_time - self.cfg["start-time"]
        total_seconds = delta.days * 24 * 3600 + delta.seconds
        if date_config['name'] == '自定义' and tried_times<self.cfg["max-retry"]/3*2:
            seat = seats[0]
        else:
            seat = random.choice(seats)
        data = f"beginTime={total_seconds}&duration={3600 * date_config['持续小时数']}&&seats[0]={seat}&seatBookers[0]={self.user_data['uid']}"

        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        print(data)
        self.resp = requests.post(self.cfg["target"], data=data, headers=headers)
        self.json = json.loads(self.resp.text)
        return self.json["CODE"], self.json["MESSAGE"] + " 座位:{}".format(seat)

    def login(self):
        logging.info('Login in')

        try:
            logging.info('开始登陆...')

            self.driver.get("https://hdu.huitu.zhishulib.com/")
            logging.debug('打开网站.')
            # 图书馆系统已接入学校统一身份认证平台(CAS)，页面会自动跳转到 sso.hdu.edu.cn
            self.wait.until(lambda d: "sso.hdu.edu.cn" in d.current_url)
            logging.debug('已跳转至统一身份认证平台.')

            self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
            logging.debug('找到用户名输入框.')

            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
            logging.debug('找到密码输入框.')

            self.driver.find_element(By.NAME, 'username').clear()
            self.driver.find_element(By.NAME, 'username').send_keys(self.un)  # 传送帐号
            logging.info('输入用户名')

            self.driver.find_element(By.CSS_SELECTOR, "input[type='password']").clear()
            self.driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys(self.pd)  # 输入密码
            logging.info('输入密码')
            logging.info('点击登录按钮')
            # 按钮文字"登    录"中含多个空格且可能被遮挡，页面内直接触发点击事件最可靠
            self.driver.execute_script("document.querySelector('button.login-button').click()")

            # 等待CAS认证完成并跳回图书馆系统域名
            WebDriverWait(self.driver, 30, 0.5).until(lambda d: "huitu.zhishulib.com" in d.current_url)
            time.sleep(5)
            cookie_list = self.driver.get_cookies()
            self.cookie = ";".join([item["name"] + "=" + item["value"] + "" for item in cookie_list])
            self.cfg["headers"]['Cookie'] = self.cookie

            logging.info("登录成功！")
        except Exception as e:
            logging.error(f"登录失败：{e}")
            return -1
        return 0

    def get_user_info(self):
        logging.info('Getting user info')

        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        try:
            resp = requests.get("https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1",
                                headers=headers)
            self.user_data = resp.json()['DATA']
            _ = self.user_data['uid']
        except Exception as e:
            logging.exception(e)
            print(self.user_data)
            print(e.__class__.__name__ + ",获取用户数据失败")
            return -1
        print("获取用户数据成功")
        return 0

    def has_existing_booking(self):
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        try:
            resp = requests.get(
                "https://hdu.huitu.zhishulib.com/Seat/Index/myBookingList?LAB_JSON=1",
                headers=headers, timeout=20)
            data = resp.json()
        except Exception as e:
            logging.exception(e)
            print("查询已有预约失败，将尝试提交预约")
            return False
        return _json_has_booking(data)

    def wechatNotice(self, message, desp=None):
        logging.info('Sending WeChat notice')

        if self.SCKey != '':
            url = 'https://sctapi.ftqq.com/{0}.send'.format(self.SCKey)
            data = {
                'title': message,
                desp: desp,
            }
            try:
                r = requests.post(url, data=data)
                if r.json()["data"]["error"] == 'SUCCESS':
                    print("Server酱通知成功")
                else:
                    print("Server酱通知失败")
            except Exception as e:
                logging.exception(e)
                print(e.__class__, "推送服务配置错误")

if __name__ == "__main__":
    logging.info('Start of the program')
    with open("user_config.yml", 'r') as f_obj:
        user_config = yaml.safe_load(f_obj)
    with open("config/basic_config.yml", 'r') as f_obj:
        basic_config = yaml.safe_load(f_obj)
    with open("config/seat_config.yml", 'r') as f_obj:
        seat_config = yaml.safe_load(f_obj)

    s = SeatAutoBooker(basic_config["SeatAutoBooker"])
    if not s.login() == 0:
        s.driver.quit()
        logging.info('Login unsuccessful')
        exit(-1)
    if not s.get_user_info() == 0:
        s.driver.quit()
        logging.info('Getting user info unsuccessful')
        exit(-1)
    if s.has_existing_booking():
        print("已有预约，结束")
        s.driver.quit()
        exit(0)
    result = s.book_favorite_seat(user_config=user_config, seat_config=seat_config)
    code, message = result if result else (-1, "多次尝试均失败")
    print("预约结果: {} {}".format(code, message))
    s.driver.quit()
    logging.info('End of the program')
