import io
import random
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated
from urllib.parse import quote
from typing import Annotated, Optional


from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo

# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ─── Auth config (เปลี่ยน SECRET_KEY ก่อน deploy!) ───────────────────────────

SECRET_KEY = "change-me-before-deploy-use-openssl-rand-hex-32"
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = 8

USERS = {"baifern999": "admin999"}  # TODO: ใช้ DB + bcrypt จริง ๆ ใน production

# Mapping สำหรับรูปธง (อัปเดตตามชื่อที่มีการรวมรอบ + VIP และ เช้า/บ่าย)
FLAG_MAPPING = {
    # 🇱🇦 ลาว (Laos)
    "ลาว EXTRA": "static/flags/laos.png",
    "ลาว TV": "static/flags/laos.png",
    "ลาวพิเศษรอบเที่ยง": "static/flags/laos.png",
    "ลาว HD": "static/flags/laos.png",
    "ลาวสตาร์": "static/flags/laos.png",
    "หวยลาวสามัคคี": "static/flags/laos.png", # ปรับตามชื่อใหม่
    "ลาวพัฒนา": "static/flags/laos.png",
    "ลาวอาเซียน": "static/flags/laos.png",
    "ลาว VIP": "static/flags/laos.png",
    "ลาวสามัคคี VIP": "static/flags/laos.png",
    "ลาว STAR VIP": "static/flags/laos.png",
    "ลาวกาชาด": "static/flags/laos.png",

    # 🇻🇳 เวียดนาม (Vietnam)
    "ฮานอยอาเซียน": "static/flags/vietnam.png",
    "ฮานอย HD": "static/flags/vietnam.png",
    "ฮานอยสตาร์": "static/flags/vietnam.png",
    "ฮานอย TV": "static/flags/vietnam.png",
    "ฮานอยกาชาด": "static/flags/vietnam.png",
    "ฮานอยพิเศษ": "static/flags/vietnam.png",
    "ฮานอยสามัคคี": "static/flags/vietnam.png",
    "ฮานอย": "static/flags/vietnam.png", # ปรับตามชื่อใหม่
    "ฮานอย VIP": "static/flags/vietnam.png",
    "ฮานอยพัฒนา": "static/flags/vietnam.png",
    "ฮานอย EXTRA": "static/flags/vietnam.png",

    # 🇯🇵 ญี่ปุ่น (Japan)
    "นิเคอิ(เช้า) + VIP": "static/flags/japan.png",
    "นิเคอิ(บ่าย) + VIP": "static/flags/japan.png",

    # 🇨🇳 จีน (China)
    "จีน(เช้า) + VIP": "static/flags/china.png",
    "จีน(บ่าย) + VIP": "static/flags/china.png",

    # 🇭🇰 ฮ่องกง (Hong Kong)
    "ฮั่งเส็ง(เช้า) + VIP": "static/flags/hongkong.png",
    "ฮั่งเส็ง(บ่าย) + VIP": "static/flags/hongkong.png",

    # 🇹🇼 ไต้หวัน (Taiwan)
    "ไต้หวัน + VIP": "static/flags/taiwan.png",

    # 🇰🇷 เกาหลีใต้ (South Korea)
    "เกาหลี + VIP": "static/flags/korea.png",

    # 🇺🇸 สหรัฐอเมริกา (USA)
    "ดาวโจนส์ + VIP": "static/flags/usa.png",
    "ดาวโจนส์ STAR": "static/flags/usa.png",

    # 🇬🇧 อังกฤษ (United Kingdom)
    "อังกฤษ + VIP": "static/flags/uk.png",

    # 🇩🇪 เยอรมนี (Germany)
    "เยอรมัน + VIP": "static/flags/germany.png",

    # 🇷🇺 รัสเซีย (Russia)
    "รัสเซีย + VIP": "static/flags/russia.png",

    # 🇸🇬 สิงคโปร์ (Singapore)
    "สิงคโปร์ + VIP": "static/flags/singapore.png",

    # 🇹🇭 ไทย (Thailand)
    "ไทยเช้า": "static/flags/thailand.png",
    "ไทยเที่ยง": "static/flags/thailand.png",
    "ไทยบ่าย": "static/flags/thailand.png",
    "ไทยเย็น": "static/flags/thailand.png",
    "ไทย": "static/flags/thailand.png",
    "ออมสิน": "static/flags/thailand.png",
    "ธกส": "static/flags/thailand.png",
    "รัฐบาล": "static/flags/thailand.png",

    # 🇮🇳 อินเดีย (India)
    "อินเดีย": "static/flags/india.png",

    # 🇲🇾 มาเลเซีย (Malaysia)
    "มาเลย์": "static/flags/malaysia.png",

    # 🇪🇬 อียิปต์ (Egypt)
    "อียิปต์": "static/flags/egypt.png",

    # 🇪🇺 ยุโรป (Europe)
    "ยูโร": "static/flags/eu.png"
}


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Cookie(default=None, alias="access_token")) -> str:
    if not token:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})


CurrentUser = Annotated[str, Depends(get_current_user)]


# ─── Image/font cache (โหลดครั้งเดียวตอน startup) ───────────────────────────

@lru_cache(maxsize=1)
def _load_bg() -> Image.Image:
    """โหลดภาพพื้นหลังครั้งเดียว แล้ว cache ไว้ใน RAM"""
    return Image.open("static/Baan-1.jpg").convert("RGBA")


@lru_cache(maxsize=16) # เพิ่มขนาด cache เผื่อโหลดหลายฟอนต์
def _load_font(size: int, font_path: str = "static/GoogleSans_17pt-Bold.ttf") -> ImageFont.FreeTypeFont:
    """Cache แต่ละขนาดและไฟล์ฟอนต์แยกกัน (ค่าเริ่มต้นคือ COOOPBL สำหรับตัวเลข)"""
    return ImageFont.truetype(font_path, size)


def _get_auto_font(draw: ImageDraw.ImageDraw, text: str, max_width: int,
                   start: int = 50, min_size: int = 20, 
                   font_path: str = "static/GoogleSans_17pt-Bold.ttf") -> ImageFont.FreeTypeFont:
    for size in range(start, min_size - 1, -1):
        font = _load_font(size, font_path)
        w = draw.textbbox((0, 0), text, font=font)[2]
        if w <= max_width:
            return font
    return _load_font(min_size, font_path)


def _bold_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
               font: ImageFont.FreeTypeFont, fill: str = "#ffca08", boldness: int = 1) -> None:
    x, y = xy
    for dx in range(-boldness, boldness + 1):
        for dy in range(-boldness, boldness + 1):
            draw.text((x + dx, y + dy), text, font=font, fill=fill)


def create_image_bytes(lottery_type: str, main1: Optional[str] = None, main2: Optional[str] = None) -> bytes:
    """
    สร้างรูปภาพในหน่วยความจำและคืนค่าเป็น bytes (PNG/JPEG)
    ไม่มีการเขียนไฟล์ลง disk เลย
    """
    # deepcopy เพื่อไม่ให้แก้ไข cached image โดยตรง
    image = deepcopy(_load_bg()).convert("RGB")
    draw  = ImageDraw.Draw(image)

    # ─── วันที่และหัวข้อ ──────────────────────────────────────────────────
    # ปรับ format วันที่เป็น วัน/เดือน (DD/MM) ตามแบบในภาพ image_7a769f.png
    text_font_path = "static/SOV_WatPhraRoop.ttf"
    #date_text = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%d/%m")
    #draw.text((25, 5 ), date_text, font=_load_font(60 ,font_path=text_font_path), fill="#000000",stroke_width=1, stroke_fill="#000000") # อาจต้องปรับพิกัด x,y ตามพื้นหลังจริง

    # ชื่อประเภทหวย (auto-fit)
    font_auto = _get_auto_font(draw, lottery_type, image.width - 400, start=70, font_path=text_font_path)
    bbox = draw.textbbox((0, 0), lottery_type, font=font_auto)
    text_width = bbox[2] - bbox[0] # คำนวณความกว้างของตัวอักษร
    x_pos = (image.width - text_width) // 2
    
    # ตำแหน่งแกน X เริ่มต้นของข้อความ (ตามโค้ดเดิมของคุณคือ x_pos + 80)
    text_start_x = x_pos + 90
    #_bold_text(draw, (text_start_x, 95), lottery_type, font_auto, fill="#000000")
    draw.text((text_start_x, 95), lottery_type, font=font_auto, fill="#000000", stroke_width=5, stroke_fill="#ffffff")
    #draw.text((text_start_x, 95),lottery_type, font_auto, fill="#000000",stroke_width=10, stroke_fill="#fff000")

    flag_path = FLAG_MAPPING.get(lottery_type)
    if flag_path:
        try:
            # โหลดรูปธง
            flag_img = Image.open(flag_path).convert("RGBA")
            
            # 1. กำหนดขนาดธง
            target_flag_width = 100   # ⬅️ ปรับขนาดความกว้างของธงที่นี่
            w_ratio = target_flag_width / flag_img.width
            target_flag_height = int(flag_img.height * w_ratio)
            flag_img = flag_img.resize((target_flag_width, target_flag_height), Image.Resampling.LANCZOS)
            
            # 2. กำหนดตำแหน่งที่วางธงให้ต่อท้ายชื่อหวย
            spacing = 20 # ⬅️ ปรับระยะห่างระหว่างตัวอักษรกับธงได้ที่นี่
            
            # คำนวณแกน X: เอาจุดเริ่มต้นข้อความ + ความกว้างข้อความ + ระยะห่าง
            flag_x = text_start_x + text_width + spacing 
            flag_y = 95  # ⬅️ แกน Y ยึดตามเดิม (ปรับขึ้นลงให้ตรงกับข้อความได้)
            
            # วางรูปธงทับลงไป
            image.paste(flag_img, (int(flag_x), int(flag_y)), flag_img)
            
        except FileNotFoundError:
            pass # ถ้าหาไฟล์รูปธงไม่เจอ ให้ข้ามการวาดธงไปเลย
    # ─── สุ่มเลขตามเงื่อนไขใหม่ ──────────────────────────────────────────────
    
    # แปลงเป็น int หากมีค่าส่งมาและเป็นตัวเลข
    m1 = int(main1) if main1 and main1.isdigit() else None
    m2 = int(main2) if main2 and main2.isdigit() else None

    # 1. กำหนดเลขหลัก 2 ตัว
    if m1 is not None and m2 is not None:
        num1, num2 = m1, m2
        # กันเหนียว: ถ้าบังเอิญกรอกเลขเดียวกันมา ให้สุ่ม num2 ใหม่
        if num1 == num2:
            available = [i for i in range(10) if i != num1]
            num2 = random.choice(available)
    elif m1 is not None:
        num1 = m1
        available = [i for i in range(10) if i != num1]
        num2 = random.choice(available)
    elif m2 is not None:
        num2 = m2
        available = [i for i in range(10) if i != num2]
        num1 = random.choice(available)
    else:
        # ถ้าไม่มีการกรอกมาเลย ให้สุ่มทั้ง 2 ตัวตามปกติ
        num1, num2 = random.sample(range(10), 2)

    # 2. นำเลขหลัก 1 ตัว วางซ้ำกัน 3 ครั้ง (รูดเน้น)
    triple_num = f"{num1}{num1}{num1}"

    # 3. วางเลขหลักทั้งสองด้วยกัน (เม็ดเดียว)
    main_pair = f"{num2}{num2}{num2}"

    # 4. สร้างเลขคู่ 4 แถวตามเงื่อนไขใหม่
    # หาตัวเลขสุ่มที่ไม่ใช่ num1 และ num2 มา 3 ตัว เพื่อรับประกันว่าเลขจะไม่ซ้ำกัน
    available_digits = [d for d in range(10) if d not in (num1, num2)]
    r1, r2, r3 = random.sample(available_digits, 3)
    
    # สร้างรายการเลข 4 แถว
    pairs_list = [
        f"{num1}{num2}", # แถวแรก: เลขหลัก 1 และ 2
        f"{num1}{r1}",   # แถวสอง: เลขหลัก 1 และสุ่มอีก 1
        f"{num2}{r2}",   # แถวสาม: เลขหลัก 2 และสุ่มอีก 1
        f"{num2}{r3}"    # แถวสี่: เลขหลัก 2 และสุ่มอีก 1
    ]

    other  = [i for i in range(10) if i not in (num1, num2)]
    extras = random.sample(other, 4)
    six    = [num1, num2] + extras
    random.shuffle(six)
    random_6 = "".join(map(str, six))

    # ─── วาดผลลัพธ์ลงบนภาพ ────────────────────────────────────────────────
    # ปรับขนาดฟอนต์ให้เข้ากับแต่ละกล่อง
    f_large  = _load_font(130)
    f_medium = _load_font(90)
    f_small  = _load_font(70)

    # หมายเหตุ: พิกัด (x, y) เป็นค่าประมาณการอ้างอิงจากโครงสร้างภาพ image_7a769f.png
    # หากตำแหน่งเบี้ยว คุณสามารถปรับตัวเลข x (แนวนอน) และ y (แนวตั้ง) ด้านล่างนี้ได้เลย
    
    # รูดเน้น 3 ตัว 
    draw.text((660, 250), triple_num, font = f_large, fill="#f9c51d",stroke_width=7, stroke_fill="#180500") 
    # รอง 3 ตัว
    draw.text((660, 450), main_pair, font = f_large, fill="#f9c51d",stroke_width=7, stroke_fill="#180500")
    
    
    # เลขคู่ 3 คู่ (สีขาว เพื่อให้อ่านง่ายบนพื้นเขียว)
    #_bold_text(draw, (400, 580), pairs_text, f_small, fill="#ffffff")
    # เลขคู่ 3 คู่ (สีขาว จัดเรียงแนวตั้ง)
    start_x = 430  # ตำแหน่งแกน X (ซ้าย-ขวา)
    start_y = 610  # ตำแหน่งแกน Y เริ่มต้นของบรรทัดแรก (บน-ล่าง)
    line_gap = 100 # ระยะห่างระหว่างบรรทัด (ถ้าชิดไปให้เพิ่มเลข ถ้าห่างไปให้ลดเลข)

    for i, pair in enumerate(pairs_list):
        draw.text((start_x, start_y + (i * line_gap)), pair, font = f_medium, fill="#da1a0c",stroke_width=5, stroke_fill="#facb2f")  
    
    # เลขวิน
    draw.text((630, 1015), random_6, font = f_small, fill="#fc6502",stroke_width=5, stroke_fill="#fed827") 

    # ─── คืนค่าเป็น bytes (ไม่เซฟไฟล์) ────────────────────────────────────
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85, optimize=True)
    buf.seek(0)
    return buf.read()

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
):
    if USERS.get(username) != password:
        raise HTTPException(status_code=400, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=create_token(username),
        httponly=True,
        samesite="lax",
        max_age=TOKEN_EXPIRE_HOURS * 3600,
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


@app.get("/", response_class=HTMLResponse)
async def lottery_page(request: Request, user: CurrentUser):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.post("/")
async def lottery_generate(
    user: CurrentUser,
    lottery_type: list[str] = Form(...),
    main1: Optional[str] = Form(None), # รับค่า Main 1
    main2: Optional[str] = Form(None), # รับค่า Main 2
):
    if not lottery_type:
        raise HTTPException(status_code=400, detail="กรุณาเลือกประเภทหวยอย่างน้อย 1 รายการ")

    # --- 1. เตรียมข้อมูลและเรียงลำดับตามเวลาก่อน (ส่วนนี้แหละครับที่หายไป) ---
    parsed_items = []
    for lt_data in lottery_type:
        # แยกเวลาและชื่อหวย (เช่น "08:25" กับ "ลาว EXTRA")
        time_str, name_str = lt_data.split("|", 1) if "|" in lt_data else ("", lt_data)
        parsed_items.append({
            "time": time_str, 
            "name": name_str
        })
    
    # เรียงลำดับจากเช้าไปดึก (ถ้าไม่มีเวลา กำหนดเป็น "99:99" เพื่อดันไปอยู่ท้ายสุด)
    parsed_items.sort(key=lambda x: x["time"] if x["time"] else "99:99")

    # ─── ไฟล์เดียว: ส่งตรง ─────────────────────────────────────────────────
    if len(parsed_items) == 1:
        item = parsed_items[0]
        time_str = item["time"]
        name_str = item["name"]
        
        filename = f"{time_str.replace(':', '.')}_{name_str}.jpg" if time_str else f"{name_str}.jpg"
        encoded_filename = quote(filename)
        
        # นำ main1, main2 ส่งเข้าไปในฟังก์ชัน
        img_bytes = create_image_bytes(name_str, main1, main2)
        return StreamingResponse(
            io.BytesIO(img_bytes),
            media_type="image/jpeg",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"},
        )

    # ─── หลายไฟล์: ZIP ใน RAM ──────────────────────────────────────────────
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # ใช้ enumerate สร้างเลขลำดับ 1, 2, 3...
        for index, item in enumerate(parsed_items, start=1):
            time_str = item["time"]
            name_str = item["name"]
            
            # --- 2. สร้างเลขลำดับ (01, 02, 03...) ไว้หน้าสุด ---
            prefix = f"{index:02d}_" 
            time_part = f"{time_str.replace(':', '.')}_" if time_str else ""
            
            # ประกอบชื่อไฟล์ (เช่น "01_08.25_ลาว EXTRA.jpg" หรือ "15_หวยรัฐบาล.jpg")
            filename = f"{prefix}{time_part}{name_str}.jpg"
            
            # นำ main1, main2 ส่งเข้าไปในฟังก์ชัน
            zf.writestr(filename, create_image_bytes(name_str, main1, main2))
    zip_buf.seek(0)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="lottery_results.zip"'},
    )


# ─── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
