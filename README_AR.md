# نسخة Cloud جاهزة — كريبتو Futures فقط

هذه النسخة جاهزة للسحابة:
- Railway
- Render
- VPS لينكس

## تدعم
- Paper Trading
- Live Trading على Binance Futures
- Telegram alerts

## لا تدعم في هذه النسخة
- الذهب / الفضة / النفط
هذه تحتاج وسيط مختلف مثل MT5 أو Broker API مستقل. إذا تبيها أجهزها لك في نسخة VPS ثانية.

## التشغيل المحلي أو على السحابة
```bash
pip install -r requirements.txt
python bot.py --config config.yaml --once
```

تشغيل مستمر:
```bash
python bot.py --config config.yaml
```

## تبديل الوضع
في `config.yaml`:
- `mode: paper`
- أو `mode: live`

## متغيرات البيئة
أضف في Railway/Render:
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

## أمر التشغيل في Railway/Render
```bash
python bot.py --config config.yaml
```

## نصيحة
ابدأ بـ `paper` أولاً.
