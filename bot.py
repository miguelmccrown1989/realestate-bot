import os
import json
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

BOT_TOKEN = os.environ['BOT_TOKEN']
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ===== تنظیمات موقعیت متن روی قالب (پیکسل) =====
# این‌ها رو با توجه به قالب خودت تغییر بده
POST_LAYOUT = {
    'size': (1080, 1080),
    'photo_box': (60, 60, 1020, 620),   # (x1, y1, x2, y2) ناحیه عکس ملک
    'texts': [
        ('title',   (60, 660), 56, '#000000'),
        ('price',   (60, 740), 48, '#d32f2f'),
        ('area',    (60, 810), 40, '#333333'),
        ('address', (60, 870), 34, '#555555'),
        ('phone',   (60, 940), 44, '#000000'),
    ]
}

STORY_LAYOUT = {
    'size': (1080, 1920),
    'photo_box': (60, 100, 1020, 900),
    'texts': [
        ('title',   (60, 960),  70, '#000000'),
        ('price',   (60, 1080), 60, '#d32f2f'),
        ('area',    (60, 1180), 50, '#333333'),
        ('address', (60, 1260), 44, '#555555'),
        ('phone',   (60, 1360), 56, '#000000'),
    ]
}
# ===============================================

def fa(text):
    """اصلاح متن فارسی برای نمایش درست"""
    return get_display(arabic_reshaper.reshape(str(text)))

def load(path, default=None):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default if default is not None else {}

def save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def tg(method, **kwargs):
    r = requests.post(f"{API}/{method}", json=kwargs, timeout=30)
    return r.json()

def get_updates(offset=None):
    params = {'timeout': 0, 'allowed_updates': '["message"]'}
    if offset:
        params['offset'] = offset
    r = requests.get(f"{API}/getUpdates", params=params, timeout=30)
    return r.json().get('result', [])

def send_message(chat_id, text):
    tg('sendMessage', chat_id=chat_id, text=text)

def send_photo(chat_id, photo_path, caption=''):
    with open(photo_path, 'rb') as f:
        requests.post(
            f"{API}/sendPhoto",
            data={'chat_id': chat_id, 'caption': caption},
            files={'photo': f},
            timeout=60
        )

def download_photo(file_id, save_path):
    r = requests.get(f"{API}/getFile", params={'file_id': file_id}).json()
    file_path = r['result']['file_path']
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    content = requests.get(url, timeout=60).content
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, 'wb') as f:
        f.write(content)

def crop_fill(img, box):
    """عکس رو داخل باکس می‌ذاره بدون کشیدگی"""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    iw, ih = img.size
    ratio = max(w / iw, h / ih)
    nw, nh = int(iw * ratio), int(ih * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return img.crop((left, top, left + w, top + h))

def render(prop, template_path, output_path, layout, font_path):
    base = Image.open(template_path).convert('RGB')
    
    # جای‌گذاری عکس ملک
    if prop.get('image') and os.path.exists(prop['image']):
        photo = Image.open(prop['image']).convert('RGB')
        photo = crop_fill(photo, layout['photo_box'])
        base.paste(photo, (layout['photo_box'][0], layout['photo_box'][1]))
    
    draw = ImageDraw.Draw(base)
    
    # نوشتن متن‌ها
    for key, (x, y), size, color in layout['texts']:
        val = prop.get(key, '')
        if not val:
            continue
        font = ImageFont.truetype(font_path, size)
        draw.text((x, y), fa(val), font=font, fill=color)
    
    base.save(output_path, quality=92)
    return output_path

def build_caption(p):
    return (
        f"{p['title']}\n"
        f"💰 قیمت: {p['price']}\n"
        f"📐 متراژ: {p['area']} متر\n"
        f"🛏 اتاق: {p['rooms']}\n"
        f"📍 {p['address']}\n"
        f"📞 {p['phone']}"
    )

HELP = """سلام 👋
دستورها:

➕ افزودن ملک:
/add عنوان|قیمت|متراژ|اتاق|آدرس|تلفن
سپس عکس ملک رو بفرست.

🖼 ساخت پست:  /post 1
📱 ساخت استوری: /story 1
📋 لیست:  /list
❌ حذف:  /del 1
"""

def main():
    state = load('state.json', {'last_update_id': 0, 'pending': {}})
    props = load('properties.json', {})
    last_id = state.get('last_update_id', 0)
    
    updates = get_updates(offset=last_id + 1 if last_id else None)
    
    for u in updates:
        last_id = u['update_id']
        msg = u.get('message')
        if not msg:
            continue
        
        chat_id = msg['chat']['id']
        text = (msg.get('text') or '').strip()
        photo = msg.get('photo')
        key = str(chat_id)
        
        try:
            if text == '/start' or text == '/help':
                send_message(chat_id, HELP)
            
            elif text.startswith('/add'):
                parts = text[4:].strip().split('|')
                if len(parts) < 6:
                    send_message(chat_id, "❌ فرمت درست:\n/add عنوان|قیمت|متراژ|اتاق|آدرس|تلفن")
                    continue
                new_id = str(max([int(k) for k in props.keys()] + [0]) + 1)
                props[new_id] = {
                    'id': new_id,
                    'title': parts[0].strip(),
                    'price': parts[1].strip(),
                    'area': parts[2].strip(),
                    'rooms': parts[3].strip(),
                    'address': parts[4].strip(),
                    'phone': parts[5].strip(),
                    'image': None,
                }
                state['pending'][key] = new_id
                save('properties.json', props)
                save('state.json', state)
                send_message(chat_id, f"✅ ملک #{new_id} ثبت شد.\nحالا عکس ملک رو بفرست 📷")
            
            elif photo:
                pid = state['pending'].get(key)
                if not pid:
                    send_message(chat_id, "اول با /add ملک رو ثبت کن.")
                    continue
                img_path = f"images/{pid}.jpg"
                download_photo(photo[-1]['file_id'], img_path)
                props[pid]['image'] = img_path
                save('properties.json', props)
                state['pending'].pop(key, None)
                save('state.json', state)
                send_message(chat_id, f"✅ عکس ملک #{pid} ذخیره شد.\nحالا /post {pid} یا /story {pid} بزن.")
            
            elif text.startswith('/post'):
                pid = text[5:].strip()
                p = props.get(pid)
                if not p:
                    send_message(chat_id, "❌ ملک پیدا نشد.")
                    continue
                out = render(p, 'templates/post.png', f'/tmp/p{pid}.jpg',
                             POST_LAYOUT, 'fonts/Vazirmatn-Bold.ttf')
                send_photo(chat_id, out, caption=build_caption(p))
            
            elif text.startswith('/story'):
                pid = text[6:].strip()
                p = props.get(pid)
                if not p:
                    send_message(chat_id, "❌ ملک پیدا نشد.")
                    continue
                out = render(p, 'templates/story.png', f'/tmp/s{pid}.jpg',
                             STORY_LAYOUT, 'fonts/Vazirmatn-Bold.ttf')
                send_photo(chat_id, out)
            
            elif text.startswith('/list'):
                if not props:
                    send_message(chat_id, "هنوز ملکی نداری.")
                else:
                    lines = [f"#{k} — {v['title']}" for k, v in props.items()]
                    send_message(chat_id, "📋 لیست املاک:\n\n" + "\n".join(lines))
            
            elif text.startswith('/del'):
                pid = text[4:].strip()
                if pid in props:
                    img = props[pid].get('image')
                    if img and os.path.exists(img):
                        os.remove(img)
                    del props[pid]
                    save('properties.json', props)
                    send_message(chat_id, f"✅ ملک #{pid} حذف شد.")
                else:
                    send_message(chat_id, "پیدا نشد.")
        
        except Exception as e:
            send_message(chat_id, f"⚠️ خطا: {e}")
    
    state['last_update_id'] = last_id
    save('state.json', state)


if __name__ == '__main__':
    main()
