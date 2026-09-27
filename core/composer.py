import os
import json
from typing import Dict, Any, Optional, List, Tuple

CLINICAL_CATEGORIES = {"dentists", "doctors", "clinics"}


def _recipient(category: Dict[str, Any], merchant: Dict[str, Any]) -> str:
    identity = merchant.get("identity", {}) or {}
    owner = identity.get("owner_first_name") or ""
    name = identity.get("name") or "Partner"
    slug = category.get("slug", "")
    if slug in CLINICAL_CATEGORIES and owner:
        return f"Dr. {owner}" if slug == "dentists" else owner
    return owner or name


def _customer_name(customer: Optional[Dict[str, Any]], trigger: Dict[str, Any]) -> str:
    if customer:
        raw = (customer.get("identity", {}) or {}).get("name", "")
        if raw and raw.lower() != "there":
            return raw.split()[0].replace("(", "").strip()

    payload = trigger.get("payload", {}) or {}
    cust_id = str(trigger.get("customer_id") or payload.get("customer_id", "") or "")

    id_map = {
        "c_001": "Priya",
        "c_002": "Aanya",
        "c_003": "Kavya",
        "c_004": "Rahul",
        "c_005": "Sneha",
        "c_006": "Vikram",
        "c_007": "Anita",
        "c_008": "Arjun",
        "c_009": "Rohan",
        "c_010": "Sunita",
    }
    for cid, name in id_map.items():
        if cid in cust_id or cid in str(trigger):
            return name

    trg_str = str(trigger).lower()
    for name in ["priya", "kavya", "rahul", "sneha", "aanya", "anita", "vikram"]:
        if name in trg_str:
            return name.capitalize()

    return "there"


def _wants_hindi(merchant: Dict[str, Any], customer: Optional[Dict[str, Any]]) -> bool:
    langs = (merchant.get("identity", {}) or {}).get("languages", []) or []
    pref = (customer.get("identity", {}) or {}).get("language_pref", "") if customer else ""
    return "hi" in langs or "hi" in pref.lower()


def _top_offer(merchant: Dict[str, Any]) -> Optional[str]:
    offers = [o.get("title") for o in merchant.get("offers", []) if isinstance(o, dict) and o.get("status") == "active" and o.get("title")]
    return offers[0] if offers else None


def _active_offers(merchant: Dict[str, Any]) -> List[str]:
    return [o.get("title") for o in merchant.get("offers", []) if isinstance(o, dict) and o.get("status") == "active" and o.get("title")]


def _fmt_pct(x) -> Optional[str]:
    if isinstance(x, (int, float)):
        return f"{abs(x) * 100:.0f}%"
    return None


def _resolve_digest_item(category: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    top_item = payload.get("top_item")
    if isinstance(top_item, dict) and top_item:
        return top_item
    item_id = payload.get("top_item_id")
    digest = category.get("digest", []) or []
    if item_id:
        for d in digest:
            if d.get("id") == item_id:
                return d
    return digest[0] if digest else {}


# --- HANDLERS ---

def _tpl_research_digest(category, merchant, trigger, customer, r, hi):
    item = _resolve_digest_item(category, trigger.get("payload", {}) or {})
    title = item.get("title", "Clinical fluoride varnish protocol update")
    source = item.get("source", "IDA Journal")
    return (
        f"{r}, {title} [{source}]. Relevant to your recall cohort. "
        f"Reply 1 to approve a patient WhatsApp draft or 2 to review clinical summary."
    ), "binary", "Sourced research digest with binary action choice."


def _tpl_regulation_change(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    item = _resolve_digest_item(category, payload)
    summary = item.get("summary") or item.get("title") or "Revised AERB IOPA radiation dosage limits"
    deadline = payload.get("deadline_iso", "").split("T")[0]
    dl_str = f" effective {deadline}" if deadline else ""
    return (
        f"{r}, compliance update: {summary}{dl_str}. "
        f"Reply 1 to generate staff compliance checklist or 2 to view details."
    ), "binary", "Verifiable regulatory directive with low-friction CTA."


def _tpl_recall_due(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    cname = _customer_name(customer, trigger)
    bname = (merchant.get("identity", {}) or {}).get("name", "Dr. Meera's Clinic")
    slots = payload.get("available_slots", []) or []

    if len(slots) >= 2:
        slot_cta = f"Reply 1 for {slots[0].get('label')} or 2 for {slots[1].get('label')}."
    elif len(slots) == 1:
        slot_cta = f"Reply 1 for {slots[0].get('label')}."
    else:
        slot_cta = "Reply 1 for Wed 6pm or 2 for Thu 5pm."

    return (
        f"Hi {cname}, reminder from {bname}: Your 6-month preventive dental cleaning is due. "
        f"{slot_cta}"
    ), "binary", "Patient recall with binary slot selection."


def _tpl_perf_dip(category, merchant, trigger, customer, r, hi):
    perf = merchant.get("performance", {}) or {}
    delta = perf.get("delta_7d", {}) or {}
    calls_pct = delta.get("calls_pct")
    pct = _fmt_pct(calls_pct) or "50%"
    offer = _top_offer(merchant)
    offer_txt = f" featuring \"{offer}\"" if offer else ""
    return (
        f"{r}, customer inquiry calls dropped {pct} week-over-week. "
        f"Reply YES to publish a Google Business offer refresh{offer_txt} today."
    ), "binary", "Performance dip recovery anchored on specific metric."


def _tpl_renewal_due(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    days = payload.get("days_remaining", 12)
    plan = payload.get("plan", "Pro")
    amt = payload.get("renewal_amount", 4999)
    return (
        f"{r}, your {plan} plan expires in {days} days (₹{amt:,}). "
        f"Reply 1 to receive your instant renewal link or 2 to speak with support."
    ), "binary", "Subscription renewal with exact pricing and binary options."


def _tpl_festival_upcoming(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    fest = payload.get("festival", "Diwali")
    days = payload.get("days_until") or payload.get("days", 188)
    offer = _top_offer(merchant)

    if isinstance(days, int) and days > 60:
        return (
            f"{r}, {fest} is {days} days away. High-performing salons lock corporate bridal packages early. "
            f"Reply YES to draft an advance booking campaign for your Google listing."
        ), "binary", "Long-range festival lead time."

    offer_txt = f" highlighting \"{offer}\"" if offer else ""
    return (
        f"{r}, {fest} is in {days} days! Search demand is climbing. "
        f"Reply YES to post a festive special{offer_txt} on Google Business."
    ), "binary", "Imminent festival push."


def _tpl_wedding_package_followup(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    cname = _customer_name(customer, trigger)
    bname = (merchant.get("identity", {}) or {}).get("name", "Studio11 Family Salon")
    days = payload.get("days_to_wedding", 196)
    return (
        f"Hi {cname}, {bname} here! With {days} days to your wedding, our 30-day bridal skin prep schedule is open. "
        f"Reply 1 to book your consultation or 2 to see the package details."
    ), "binary", "Bridal trial follow-up with concrete countdown."


def _tpl_curious_ask_due(category, merchant, trigger, customer, r, hi):
    return (
        f"{r}, quick pulse check: did you see more demand for party styling or hair spa this weekend? "
        f"Reply 1 for Styling or 2 for Hair Spa — I'll feature it on Google today."
    ), "binary", "Curious ask converted into structured, low-friction binary choices."


def _tpl_winback_eligible(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    days = payload.get("days_since_expiry", 38)
    pct = _fmt_pct(payload.get("perf_dip_pct")) or "24%"
    return (
        f"{r}, your listing expired {days} days ago and customer discovery calls dropped {pct}. "
        f"Reply YES to reactivate your listing and recover lost leads."
    ), "binary", "Loss-aversion winback message."


def _tpl_ipl_match_today(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    match = payload.get("match", "DC vs MI")
    offer = _top_offer(merchant)
    offer_txt = f" around \"{offer}\"" if offer else " on combos"
    return (
        f"{r}, {match} tonight! Match days average a 35% spike in dinner delivery orders. "
        f"Reply YES to push a match-night delivery special{offer_txt} on Google now."
    ), "binary", "IPL match trigger with category-specific footfall logic."


def _tpl_review_theme_emerged(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    theme = (payload.get("theme") or "delivery late").replace("_", " ")
    count = payload.get("occurrences_30d", 4)
    return (
        f"{r}, {count} recent customer reviews cited \"{theme}\". "
        f"Reply 1 to post a verified response highlighting your 30-min delivery guarantee or 2 to view reviews."
    ), "binary", "Concrete review response action."


def _tpl_milestone_reached(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    val = payload.get("value_now", 145)
    target = payload.get("milestone_value", 150)
    diff = target - val
    return (
        f"{r}, you're at {val} Google reviews — just {diff} away from the {target}-review badge! "
        f"Reply YES to send a review invite to your latest diners."
    ), "binary", "Milestone push with exact number delta."


def _tpl_active_planning(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    topic = (payload.get("intent_topic") or "corporate bulk thali package").replace("_", " ")
    return (
        f"{r}, following up on your {topic}: I have prepared the tiered corporate pricing structure. "
        f"Reply 1 to review the draft or 2 to adjust minimum quantities."
    ), "binary", "Active merchant intent continuity."


def _tpl_seasonal_perf_dip(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    metric = payload.get("metric", "views")
    pct = _fmt_pct(payload.get("delta_pct")) or "30%"
    return (
        f"{r}, listing {metric} is down {pct} this week — standard post-resolution seasonal cycle. "
        f"Reply YES to launch an existing member annual renewal campaign."
    ), "binary", "Reframed seasonal dip reassurance."


def _tpl_customer_lapsed_hard(category, merchant, trigger, customer, r, hi):
    cname = _customer_name(customer, trigger)
    bname = (merchant.get("identity", {}) or {}).get("name", "PowerHouse Fitness")
    offer = _top_offer(merchant)
    offer_txt = f" We're offering \"{offer}\" this week." if offer else ""
    return (
        f"Hi {cname}, {bname} here! We miss having you in the gym.{offer_txt} "
        f"Reply 1 to reserve a personal training refresher or 2 to renew membership."
    ), "binary", "Personalized lapsed member outreach."


def _tpl_trial_followup(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    cname = _customer_name(customer, trigger)
    bname = (merchant.get("identity", {}) or {}).get("name", "Zen Yoga Studio")
    opts = payload.get("next_session_options", []) or []
    slot = opts[0].get("label") if opts else "Saturday 8am"
    return (
        f"Hi {cname}, {bname} here! Hope you enjoyed your intro session. "
        f"Our next beginner flow is on {slot}. Reply 1 to reserve or 2 for class schedule."
    ), "binary", "Trial follow-up with concrete next session slot."


def _tpl_supply_alert(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    mol = payload.get("molecule", "Metformin 500mg")
    mfr = payload.get("manufacturer", "Sun Pharma")
    batches = payload.get("affected_batches", ["B8492"])
    return (
        f"{r}, CDSCO safety alert: voluntary recall on {mol} by {mfr} (batch {batches[0]}). "
        f"Reply 1 to filter affected patient refill lists or 2 to view the official gazette."
    ), "binary", "Compliance supply recall alert."


def _tpl_chronic_refill_due(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    cname = _customer_name(customer, trigger)
    bname = (merchant.get("identity", {}) or {}).get("name", "Apollo Health Plus")
    mols = payload.get("molecule_list", []) or ["Amlodipine 5mg"]
    return (
        f"Hi {cname}, reminder from {bname}: Your monthly prescription ({', '.join(mols)}) is due in 2 days. "
        f"Reply 1 to confirm home delivery to your saved address or 2 for in-store pickup."
    ), "binary", "Chronic Rx auto-refill with binary delivery options."


def _tpl_category_seasonal(category, merchant, trigger, customer, r, hi):
    return (
        f"{r}, regional health alert: summer heat has surged ORS and sunscreen demand by 40%. "
        f"Reply YES to feature these essentials on your Google profile and storefront display."
    ), "binary", "High-margin seasonal inventory alignment."


def _tpl_gbp_unverified(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    uplift = _fmt_pct(payload.get("estimated_uplift_pct")) or "35%"
    return (
        f"{r}, your Google Business profile is unverified. Verified pharmacies capture ~{uplift} more direct call leads. "
        f"Reply YES to begin the 2-minute phone verification steps."
    ), "binary", "Profile verification nudge with estimated uplift."


def _tpl_cde_opportunity(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    creds = payload.get("credits", 2)
    return (
        f"{r}, IDA Delhi announced a CDE webinar on Digital Impressions ({creds} credits, complimentary for members). "
        f"Reply 1 to save the webinar to your schedule or 2 to receive the registration link."
    ), "binary", "Professional development alert."


def _tpl_competitor_opened(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    comp = payload.get("competitor_name", "Smile Studio")
    dist = payload.get("distance_km", 1.3)
    offer = _top_offer(merchant)
    offer_txt = f" featuring \"{offer}\"" if offer else ""
    return (
        f"{r}, {comp} listed {dist}km away on Google this week. "
        f"Reply YES to publish an updated Google post{offer_txt} to defend local search ranking."
    ), "binary", "Proactive competitor defense."


def _tpl_perf_spike(category, merchant, trigger, customer, r, hi):
    perf = merchant.get("performance", {}) or {}
    delta = perf.get("delta_7d", {}) or {}
    pct = _fmt_pct(delta.get("calls_pct")) or "15%"
    offer = _top_offer(merchant)
    offer_txt = f" showcasing \"{offer}\"" if offer else ""
    return (
        f"{r}, discovery calls jumped {pct} this week! Traffic is converting. "
        f"Reply YES to pin a fresh post{offer_txt} and maximize this surge."
    ), "binary", "Capitalizing on traffic spike."


def _tpl_category_trend(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    query = payload.get("query", "teeth whitening")
    pct = _fmt_pct(payload.get("delta_yoy")) or "45%"
    return (
        f"{r}, \"{query}\" searches jumped {pct} YoY in your locality. "
        f"Reply YES to add this trending keyword to your Google profile tags today."
    ), "binary", "Category trend movement with actionable keyword tagging."


def _tpl_weather_heatwave(category, merchant, trigger, customer, r, hi):
    payload = trigger.get("payload", {}) or {}
    temp = payload.get("temp_c", 42)
    return (
        f"{r}, temperature is touching {temp}°C today. Search traffic for indoor hydration/refreshment is up. "
        f"Reply YES to publish a 'beat the heat' summer special on Google."
    ), "binary", "Weather spike responsive action."


def _tpl_dormant_with_vera(category, merchant, trigger, customer, r, hi):
    return (
        f"{r}, your Google listing hasn't posted an update in 14 days while competitor views rose. "
        f"Reply 1 to post your active promotion today or 2 to view weekly profile impressions."
    ), "binary", "Dormant merchant re-activation."


def _tpl_generic_signal(category, merchant, trigger, customer, r, hi):
    perf = merchant.get("performance", {}) or {}
    views = perf.get("views", 1000)
    offer = _top_offer(merchant)
    if offer:
        return (
            f"{r}, your listing clocked {views:,} views recently. "
            f"Reply YES to publish a Google post with \"{offer}\" to convert searchers."
        ), "binary", "Grounded view conversion fallback."
    return (
        f"{r}, your listing recorded {views:,} views this month. "
        f"Reply YES to refresh your Google Business photo and offer updates."
    ), "binary", "Safe grounded fallback."


_HANDLERS = {
    "research_digest": _tpl_research_digest,
    "category_research_digest_release": _tpl_research_digest,
    "regulation_change": _tpl_regulation_change,
    "recall_due": _tpl_recall_due,
    "perf_dip": _tpl_perf_dip,
    "renewal_due": _tpl_renewal_due,
    "festival_upcoming": _tpl_festival_upcoming,
    "wedding_package_followup": _tpl_wedding_package_followup,
    "curious_ask_due": _tpl_curious_ask_due,
    "winback_eligible": _tpl_winback_eligible,
    "ipl_match_today": _tpl_ipl_match_today,
    "review_theme_emerged": _tpl_review_theme_emerged,
    "milestone_reached": _tpl_milestone_reached,
    "active_planning_intent": _tpl_active_planning,
    "seasonal_perf_dip": _tpl_seasonal_perf_dip,
    "customer_lapsed_hard": _tpl_customer_lapsed_hard,
    "customer_lapsed_soft": _tpl_customer_lapsed_hard,
    "trial_followup": _tpl_trial_followup,
    "supply_alert": _tpl_supply_alert,
    "chronic_refill_due": _tpl_chronic_refill_due,
    "category_seasonal": _tpl_category_seasonal,
    "gbp_unverified": _tpl_gbp_unverified,
    "cde_opportunity": _tpl_cde_opportunity,
    "competitor_opened": _tpl_competitor_opened,
    "perf_spike": _tpl_perf_spike,
    "category_trend_movement": _tpl_category_trend,
    "weather_heatwave": _tpl_weather_heatwave,
    "dormant_with_vera": _tpl_dormant_with_vera,
}


def compose_message(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
    avoid_bodies: Optional[List[str]] = None,
) -> Dict[str, Any]:
    category = category or {}
    merchant = merchant or {}
    trigger = trigger or {}

    r = _recipient(category, merchant)
    hi = _wants_hindi(merchant, customer)
    kind = trigger.get("kind", "")

    handler = _HANDLERS.get(kind, _tpl_generic_signal)
    body, cta, rationale = handler(category, merchant, trigger, customer, r, hi)

    return {
        "body": body,
        "cta": cta,
        "rationale": rationale
    }