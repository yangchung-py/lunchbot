import os
import requests
import argparse
import schedule
import time
import re

from datetime import datetime
from instagrapi import Client
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
IG_CREDENTIAL_PATH = "./ig_settings.json"
IG_IMAGE_PATH = "./menu"

class Bot:
    def __init__(self):
        self._cl = Client()
        if os.path.exists(IG_CREDENTIAL_PATH):
            self._cl.load_settings(IG_CREDENTIAL_PATH)
        self._cl.login(IG_USERNAME, IG_PASSWORD)
        self._cl.dump_settings(IG_CREDENTIAL_PATH)

    def upload_story(self, image_path):
        print("Uploading story...")
        self._cl.photo_upload_to_story(image_path)
        print("Story uploaded successfully.")

def fetch_and_upload_menu():
    bot = Bot()
    
    # 중식 메뉴 처리
    lunch_menu = get_meal_menu(2)
    if lunch_menu is not None:
        lunch_image_path = create_menu_image(lunch_menu, "중식", "_lunch")
        upload_story(bot, lunch_image_path)
    
    # 10초 대기
    time.sleep(10)
    
    # 석식 메뉴 처리
    dinner_menu = get_meal_menu(3)
    if dinner_menu is not None:
        dinner_image_path = create_menu_image(dinner_menu, "석식", "_dinner")
        upload_story(bot, dinner_image_path)

def get_meal_menu(meal_code):
    today = datetime.now().strftime('%Y%m%d')
    url = f'https://open.neis.go.kr/hub/mealServiceDietInfo?Type=json&pSize=100&ATPT_OFCDC_SC_CODE=B10&SD_SCHUL_CODE=7010208&MMEAL_SC_CODE={meal_code}&MLSV_YMD={today}'
    
    try:
        print(f"Fetching {'lunch' if meal_code == 2 else 'dinner'} menu...")
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()

        if 'mealServiceDietInfo' in data:
            menu_items = data['mealServiceDietInfo'][1]['row'][0]['DDISH_NM'].split('<br/>')
            # 괄호와 그 안의 내용 제거
            cleaned_menu = [re.sub(r'\s*\([^)]*\)', '', item.replace('y', '').strip()) for item in menu_items]
            menu = '\n'.join(cleaned_menu)
            print(f"{'Lunch' if meal_code == 2 else 'Dinner'} menu fetched successfully.")
        else:
            menu = None
            print(f"{'Lunch' if meal_code == 2 else 'Dinner'} menu not found.")
    except Exception as e:
        menu = None
        print(f"Error fetching meal menu: {e}")

    return menu

def create_menu_image(menu_text, meal_type, suffix):
    if menu_text is None:
        return None

    image_width = 1080
    image_height = 1920
    background_color = (255, 255, 255)
    text_color = (0, 0, 0)
    font_size = 60

    image = Image.new('RGB', (image_width, image_height), background_color)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("font.ttf", font_size)

    # 메뉴 타입과 메뉴 내용을 합침
    full_text = f"{meal_type}\n\n{menu_text}"
    
    text_bbox = draw.textbbox((0, 0), full_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (image_width - text_width) / 2
    y = (image_height - text_height) / 2

    draw.text((x, y), full_text, fill=text_color, font=font)

    today = datetime.now().strftime('%Y%m%d')
    image_path = f'{IG_IMAGE_PATH}/{today}{suffix}.jpg'
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    image.save(image_path)
    print(f"Menu image created: {image_path}")
    return image_path

def create_initiated_image():
    image_width = 1080
    image_height = 1920
    background_color = (255, 255, 255)
    text_color = (0, 0, 0)
    font_size = 60

    image = Image.new('RGB', (image_width, image_height), background_color)
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.truetype("font.ttf", font_size)
    except:
        font = ImageFont.load_default()

    initiated_text = 'initiated'
    text_bbox = draw.textbbox((0, 0), initiated_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (image_width - text_width) / 2
    y = (image_height - text_height) / 2

    draw.text((x, y), initiated_text, fill=text_color, font=font)

    initiated_image_path = f'{IG_IMAGE_PATH}/initiated.jpg'
    os.makedirs(os.path.dirname(initiated_image_path), exist_ok=True)
    image.save(initiated_image_path)
    return initiated_image_path

def upload_story(bot, image_path):
    if image_path is not None:
        bot.upload_story(image_path)

def job():
    fetch_and_upload_menu()

schedule.every().monday.at("07:00").do(job)
schedule.every().tuesday.at("07:00").do(job)
schedule.every().wednesday.at("07:00").do(job)
schedule.every().thursday.at("07:00").do(job)
schedule.every().friday.at("07:00").do(job)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload Instagram story")
    parser.add_argument("--uploadnow", action="store_true", help="Upload the story immediately")
    args = parser.parse_args()

    bot = Bot()
    #initiated_image_path = create_initiated_image()
    #bot.upload_story(initiated_image_path)
    #print("Initiated image uploaded successfully.")

    if args.uploadnow:
        fetch_and_upload_menu()
    else:
        print("Program initiated.")
        
        next_run = schedule.next_run()
        print(f"Next scheduled run at: {next_run}")

        while True:
            schedule.run_pending()
            time.sleep(1)
