"""Bilingual message catalog (English / Arabic).

The API stays language-neutral: analysis output carries stable codes plus
pre-formatted parameters, and the client renders them in the chosen language.
That way switching language is instant and never needs a refetch, and wording
changes happen in one place instead of being duplicated per locale.

Templates use a single `{value}` placeholder so the identical string works in
Python's `str.format` and in the browser.
"""
from __future__ import annotations

LANGUAGES = ("en", "ar")
DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    # ---- entry reasons (strategy) --------------------------------------
    "pullback_detected": {"en": "Controlled pullback detected", "ar": "تصحيح سعري منضبط"},
    "reclaim_confirmed": {"en": "VWAP + EMA reclaim confirmed", "ar": "تأكيد استعادة VWAP والمتوسطات"},
    "volume_confirmed": {"en": "Reclaim volume confirmed", "ar": "تأكيد حجم التداول عند الاستعادة"},
    "rvol": {"en": "RVOL {value}", "ar": "الحجم النسبي {value}"},
    "vwap_extension": {"en": "VWAP extension only {value}", "ar": "الامتداد عن VWAP {value} فقط"},
    "spread": {"en": "Spread {value}", "ar": "فرق السعر {value}"},

    # ---- rejection reasons (strategy / scanner) ------------------------
    "insufficient_history": {"en": "Insufficient intraday history", "ar": "سجل تداول يومي غير كافٍ"},
    "price_out_of_range": {"en": "Price outside allowed range", "ar": "السعر خارج النطاق المسموح"},
    "move_out_of_range": {"en": "Move too weak or already overextended", "ar": "الحركة ضعيفة أو ممتدة أكثر من اللازم"},
    "spread_too_wide": {"en": "Spread too wide", "ar": "فرق السعر واسع جداً"},
    "rvol_too_low": {"en": "RVOL below minimum", "ar": "الحجم النسبي أقل من الحد الأدنى"},
    "vwap_extended": {"en": "FOMO block: too far above VWAP", "ar": "حظر الاندفاع: بعيد جداً فوق VWAP"},
    "ema20_extended": {"en": "FOMO block: too far above EMA20", "ar": "حظر الاندفاع: بعيد جداً فوق EMA20"},
    "bar_too_large": {"en": "FOMO block: current 1m candle too large", "ar": "حظر الاندفاع: شمعة الدقيقة كبيرة جداً"},
    "no_pullback": {"en": "No controlled pullback yet", "ar": "لا يوجد تصحيح منضبط بعد"},
    "no_reclaim": {"en": "No VWAP/EMA reclaim confirmation", "ar": "لا يوجد تأكيد لاستعادة VWAP/EMA"},
    "no_volume_confirm": {"en": "Reclaim volume not confirmed", "ar": "حجم الاستعادة غير مؤكد"},
    "stop_too_wide": {"en": "Required stop is too wide", "ar": "وقف الخسارة المطلوب واسع جداً"},
    "regime_block": {"en": "Market regime block: SPY/QQQ not supportive", "ar": "حظر حالة السوق: SPY/QQQ غير داعمين"},

    # ---- bull case (intelligence) --------------------------------------
    "above_vwap": {"en": "Price above VWAP", "ar": "السعر فوق VWAP"},
    "ema_bullish": {"en": "EMA structure bullish", "ar": "هيكل المتوسطات صاعد"},
    "strong_rvol": {"en": "Strong RVOL {value}", "ar": "حجم نسبي قوي {value}"},
    "healthy_rvol": {"en": "Healthy RVOL {value}", "ar": "حجم نسبي جيد {value}"},
    "pullback_done": {"en": "Controlled pullback completed", "ar": "اكتمل التصحيح المنضبط"},
    "reclaim_done": {"en": "Reclaim confirmed", "ar": "تأكيد الاستعادة"},
    "tight_spread": {"en": "Tight spread", "ar": "فرق سعر ضيق"},

    # ---- bear case (intelligence) --------------------------------------
    "overextended": {"en": "Overextended above VWAP", "ar": "ممتد بإفراط فوق VWAP"},
    "large_move": {"en": "Large day move; reversal risk elevated", "ar": "حركة يومية كبيرة؛ مخاطر الانعكاس مرتفعة"},
    "wide_spread": {"en": "Wide spread", "ar": "فرق سعر واسع"},
    "weak_rvol": {"en": "Weak relative volume", "ar": "حجم نسبي ضعيف"},
    "no_clean_pullback": {"en": "No clean pullback yet", "ar": "لا يوجد تصحيح واضح بعد"},
    "reclaim_missing": {"en": "Reclaim not confirmed", "ar": "الاستعادة غير مؤكدة"},

    # ---- decision thesis ------------------------------------------------
    "thesis_arm": {
        "en": "High-quality momentum setup. Wait for second confirmation; do not chase.",
        "ar": "نموذج زخم عالي الجودة. انتظر التأكيد الثاني ولا تطارد السعر.",
    },
    "thesis_watch": {
        "en": "Promising setup, but timing or risk quality is not yet strong enough.",
        "ar": "نموذج واعد، لكن التوقيت أو جودة المخاطرة غير كافية بعد.",
    },
    "thesis_avoid": {
        "en": "Current reward/risk or entry timing does not justify a trade.",
        "ar": "نسبة العائد إلى المخاطرة أو توقيت الدخول لا يبرران الدخول.",
    },

    # ---- market brief ---------------------------------------------------
    "brief_risk_on": {
        "en": "SPY and QQQ are supportive of long momentum setups.",
        "ar": "SPY و QQQ داعمان لنماذج الزخم الشرائية.",
    },
    "brief_mixed": {
        "en": "Broad market confirmation is mixed; demand higher-quality entries.",
        "ar": "تأكيد السوق العام متباين؛ اشترط جودة دخول أعلى.",
    },
    "brief_risk_off": {
        "en": "Broad market is not supportive; new long entries should be blocked or rare.",
        "ar": "السوق العام غير داعم؛ يجب حظر عمليات الشراء الجديدة أو تقليلها.",
    },

    # ---- data-source stubs ----------------------------------------------
    "catalyst_missing": {"en": "News/catalyst provider not connected yet.", "ar": "مزود الأخبار والمحفزات غير متصل بعد."},
    "insider_missing": {"en": "SEC insider feed not connected yet.", "ar": "تغذية تداولات الداخليين (SEC) غير متصلة بعد."},

    # ---- dashboard chrome ------------------------------------------------
    "app_tagline": {"en": "AI Trading Intelligence • Paper First", "ar": "ذكاء تداول اصطناعي • تداول تجريبي أولاً"},
    "loading": {"en": "LOADING", "ar": "جاري التحميل"},
    "market_intelligence": {"en": "MARKET INTELLIGENCE", "ar": "ذكاء السوق"},
    "building_brief": {"en": "Building market brief…", "ar": "جاري إعداد ملخص السوق…"},
    "analyzing": {"en": "Analyzing broad market, liquidity and entry quality.", "ar": "تحليل السوق العام والسيولة وجودة الدخول."},
    "label_market": {"en": "MARKET", "ar": "السوق"},
    "label_equity": {"en": "EQUITY", "ar": "رأس المال"},
    "label_daily_risk": {"en": "DAILY RISK", "ar": "المخاطرة اليومية"},
    "label_auto_engine": {"en": "AUTO ENGINE", "ar": "المحرك التلقائي"},
    "buying_power": {"en": "Buying power {value}", "ar": "القوة الشرائية {value}"},
    "regime_label": {"en": "SPY/QQQ {value}", "ar": "SPY/QQQ {value}"},
    "supportive": {"en": "supportive", "ar": "داعم"},
    "blocking": {"en": "blocking", "ar": "حاظر"},
    "guard_ok": {"en": "Guard OK", "ar": "الحماية سليمة"},
    "guard_tripped": {"en": "DAILY LOSS GUARD", "ar": "تفعّل حد الخسارة اليومي"},
    "armed_label": {"en": "Armed {value}", "ar": "مُسلّح {value}"},
    "state_on": {"en": "ON", "ar": "مفعّل"},
    "state_off": {"en": "OFF", "ar": "متوقف"},
    "market_open": {"en": "OPEN", "ar": "مفتوح"},
    "market_closed": {"en": "CLOSED", "ar": "مغلق"},
    "mode_simulation": {"en": "SIMULATION", "ar": "محاكاة"},
    "mode_paper": {"en": "PAPER LIVE", "ar": "تجريبي مباشر"},
    "smart_radar": {"en": "Smart Radar", "ar": "الرادار الذكي"},
    "radar_sub": {"en": "Quality first: timing + liquidity + structure + risk", "ar": "الجودة أولاً: التوقيت + السيولة + الهيكل + المخاطرة"},
    "tap_refresh": {"en": "Tap REFRESH INTELLIGENCE to analyze.", "ar": "اضغط تحديث التحليل للبدء."},
    "running_engine": {"en": "Running intelligence engine…", "ar": "جاري تشغيل محرك التحليل…"},
    "no_setups": {"en": "No setups found.", "ar": "لا توجد فرص حالياً."},
    "names_count": {"en": "{value} names", "ar": "{value} سهم"},
    "kill_switch": {"en": "KILL SWITCH", "ar": "إيقاف طارئ"},
    "refresh": {"en": "REFRESH INTELLIGENCE", "ar": "تحديث التحليل"},
    "col_price": {"en": "PRICE", "ar": "السعر"},
    "col_move": {"en": "MOVE", "ar": "الحركة"},
    "col_rvol": {"en": "RVOL", "ar": "الحجم النسبي"},
    "col_intel": {"en": "INTEL", "ar": "التقييم"},
    "col_entry": {"en": "ENTRY", "ar": "الدخول"},
    "col_stop": {"en": "STOP", "ar": "الوقف"},
    "col_target": {"en": "TARGET", "ar": "الهدف"},
    "action_arm": {"en": "ARM", "ar": "دخول"},
    "action_watch": {"en": "WATCH", "ar": "مراقبة"},
    "action_avoid": {"en": "AVOID", "ar": "تجنب"},
    "factor_technical": {"en": "TECHNICAL", "ar": "فني"},
    "factor_liquidity": {"en": "LIQUIDITY", "ar": "السيولة"},
    "factor_timing": {"en": "TIMING", "ar": "التوقيت"},
    "factor_risk": {"en": "RISK", "ar": "المخاطرة"},
    "chip_catalyst": {"en": "Catalyst: {value}", "ar": "المحفز: {value}"},
    "chip_insider": {"en": "Insider: {value}", "ar": "الداخليون: {value}"},
    "chip_risk": {"en": "Risk {value}", "ar": "المخاطرة {value}"},
    "unverified": {"en": "UNVERIFIED", "ar": "غير مُتحقق"},
    "headline_risk_on": {"en": "Market supports selective longs", "ar": "السوق يدعم شراءً انتقائياً"},
    "headline_mixed": {"en": "Mixed tape: demand A-grade setups", "ar": "سوق متباين: اشترط نماذج من الدرجة A"},
    "headline_risk_off": {"en": "Defensive mode: protect capital", "ar": "وضع دفاعي: احمِ رأس المال"},
    "module_smart_radar": {"en": "smart radar", "ar": "الرادار الذكي"},
    "module_smart_map": {"en": "smart map", "ar": "الخريطة الذكية"},
    "module_risk_engine": {"en": "risk engine", "ar": "محرك المخاطرة"},
    "module_market_regime": {"en": "market regime", "ar": "حالة السوق"},
    "module_catalyst_feed": {"en": "catalyst feed", "ar": "تغذية المحفزات"},
    "module_insider_sec": {"en": "insider sec", "ar": "تداولات الداخليين"},
    "module_paper_execution": {"en": "paper execution", "ar": "التنفيذ التجريبي"},
    "module_autonomous_entry": {"en": "autonomous entry", "ar": "دخول تلقائي"},
    "module_autonomous_exit": {"en": "autonomous exit", "ar": "خروج تلقائي"},
    "lang_toggle": {"en": "عربي", "ar": "EN"},
    "dash": {"en": "—", "ar": "—"},
}


def render(code: str, params: dict | None = None, lang: str = DEFAULT_LANGUAGE) -> str:
    """Render a message code. Unknown codes fall back to the code itself."""
    entry = MESSAGES.get(code)
    if not entry:
        return code
    template = entry.get(lang) or entry[DEFAULT_LANGUAGE]
    return template.format(**params) if params else template


class MessageList:
    """Collects message codes and renders them, so codes and text never diverge."""

    def __init__(self):
        self.codes: list[dict] = []

    def add(self, code: str, **params) -> None:
        self.codes.append({"code": code, "params": params} if params else {"code": code})

    def __len__(self) -> int:
        return len(self.codes)

    def __bool__(self) -> bool:
        return bool(self.codes)

    def texts(self, lang: str = DEFAULT_LANGUAGE) -> list[str]:
        return [render(item["code"], item.get("params"), lang) for item in self.codes]
