"""
ops/reality_verifier.py - Zura Reality, Geography & Mathematical Truth Engine
Per Zura Charter v2 & Executive Directive:
Prevents AI hallucinations, false accounting, and geographic absurdities in Threads posts:
1. Mathematical Verification: Deterministically audits salary allocations, expense breakdowns,
   and savings targets. Rejects any post where numbers don't add up (anti-Meta.ai audit roast).
2. Indonesian Logistics & Geographic Realities: Blocks impossible transit (e.g. KRL in Surabaya)
   and absurd living costs (e.g. Rp 300k boarding in Sudirman).
3. Contextual Coherence: Ensures dilemmas and living arrangements are grounded in realistic
   Indonesian working-class economics.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("RealityVerifier")

# Transport systems and their valid regions
TRANSIT_REGIONS = {
    "krl": ["jakarta", "bogor", "depok", "tangerang", "bekasi", "jabodetabek", "yogyakarta", "jogja", "solo", "klaten"],
    "commuter line": ["jakarta", "bogor", "depok", "tangerang", "bekasi", "jabodetabek", "yogyakarta", "jogja", "solo", "klaten", "surabaya", "sidoarjo", "pasuruan", "blitar"],
    "mrt": ["jakarta", "jaksel", "jakpus", "tangsel", "jabodetabek"],
    "lrt": ["jakarta", "jaksel", "jakpus", "jaktim", "bekasi", "depok", "palembang", "jabodetabek"],
    "jaklingko": ["jakarta", "jakpus", "jaksel", "jakbar", "jaktim", "jakut", "jabodetabek"],
    "transjakarta": ["jakarta", "jakpus", "jaksel", "jakbar", "jaktim", "jakut", "jabodetabek", "tangerang", "depok", "bekasi"],
    "tj": ["jakarta", "jakpus", "jaksel", "jakbar", "jaktim", "jakut", "jabodetabek"]
}

# Cities not having electric urban rail (KRL)
NON_KRL_CITIES = [
    "surabaya", "bandung", "medan", "semarang", "makassar", "palembang",
    "denpasar", "bali", "malang", "balikpapan", "samarinda", "batam"
]


def parse_rupiah_amount(raw_str: str) -> Optional[int]:
    """
    Parses Indonesian currency expressions into exact integer IDR.
    Examples:
    '8,5jt' -> 8500000
    '8.5 juta' -> 8500000
    '500rb' -> 500000
    '500 ribu' -> 500000
    '2.000.000' -> 2000000
    '150k' -> 150000
    """
    cleaned = raw_str.lower().strip()
    cleaned = cleaned.replace("rp", "").replace("idr", "").strip()

    # Juta / Jt match: e.g. 8.5jt, 8,5 juta, 10jt
    m_jt = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:jt|juta)", cleaned)
    if m_jt:
        num = float(m_jt.group(1).replace(",", "."))
        return int(round(num * 1_000_000))

    # Ribu / Rb / K match: e.g. 500rb, 750 ribu, 250k
    m_rb = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:rb|ribu|k)", cleaned)
    if m_rb:
        num = float(m_rb.group(1).replace(",", "."))
        return int(round(num * 1_000))

    # Standard digit format with dot thousand separator: e.g. 2.500.000
    clean_digits = re.sub(r"[^\d]", "", cleaned)
    if clean_digits:
        val = int(clean_digits)
        # Avoid treating years (e.g. 2026) or single digits as currency unless > 10000
        if val >= 10_000:
            return val

    return None


def audit_financial_math(text: str) -> Dict[str, Any]:
    """
    Deterministically audits financial breakdown claims in text.
    Extracts stated income and expense allocations, then computes variance.
    """
    # 1. Detect Stated Income (Gaji / Pendapatan / Take Home Pay)
    income_patterns = [
        r"(?:gaji|penghasilan|pendapatan|thp|take home pay|gajiku|gaji gue|gaji gua)\s*(?:sebesar|nya|:)?\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        r"(?:dapet|kantongin|masuk)\s*([0-9.,]+\s*(?:jt|juta))\s*(?:per bulan|sebulan|tiap bulan)?"
    ]

    stated_income = None
    for pat in income_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = parse_rupiah_amount(m.group(1))
            if val and val >= 1_000_000:  # Minimum realistic salary
                stated_income = val
                break

    # If no explicit salary breakdown is being discussed, math audit is not applicable
    if not stated_income:
        return {
            "has_budget_breakdown": False,
            "is_valid": True,
            "stated_income": None,
            "notes": "No explicit salary allocation breakdown detected."
        }

    # 2. Extract Expense & Allocation Line Items
    allocation_categories = {
        "kos": r"(?:kos|kost|kosan|sewa kamar)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "kontrakan": r"(?:kontrakan|sewa rumah)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "makan": r"(?:makan|konsumsi|sembako|dapur)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "transport": r"(?:transport|bensin|ongkos|krl|ojol)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "kirim_ortu": r"(?:kirim ortu|orang tua|jatah ortu|keluarga)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "cicilan_paylater": r"(?:cicilan|paylater|kredivo|spaylater|utang)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "tabungan": r"(?:nabung|tabungan|invest|investasi|reksadana)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)",
        "jajan_nongki": r"(?:jajan|ngopi|nongki|hiburan)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)"
    }

    found_allocations = {}
    for cat, pat in allocation_categories.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            amt = parse_rupiah_amount(m.group(1))
            if amt and amt > 0:
                found_allocations[cat] = amt

    # If fewer than 2 categories mentioned, it's not a formal budget breakdown
    if len(found_allocations) < 2:
        return {
            "has_budget_breakdown": False,
            "is_valid": True,
            "stated_income": stated_income,
            "found_items": found_allocations,
            "notes": "Single item mention, not a full budget audit."
        }

    total_allocated = sum(found_allocations.values())
    variance = stated_income - total_allocated
    tolerance = 100_000  # Allow minor Rp 100k rounding difference

    is_exact_or_balanced = abs(variance) <= tolerance
    is_tekor = variance < -tolerance

    flaw_msg = ""
    if is_tekor:
        flaw_msg = (
            f"CACAT HITUNG / DEFISIT: Klaim gaji Rp {stated_income:,} tapi total rincian pengeluaran "
            f"Rp {total_allocated:,} (TEKOR Rp {abs(variance):,} tanpa sumber dana tambahan!). "
            "Netizen akan langsung memanggil @meta.ai dan membongkar salah hitung ini!"
        )
    elif variance > tolerance * 5:
        flaw_msg = (
            f"SELISIH DANA GHOIB: Klaim gaji Rp {stated_income:,} namun total rincian hanya "
            f"Rp {total_allocated:,} (Sisa Rp {variance:,} tidak dijelaskan ke mana larinya). "
            "Netizen akan menuduh salah hitung atau pos pengeluaran disembunyikan!"
        )

    return {
        "has_budget_breakdown": True,
        "is_valid": is_exact_or_balanced,
        "stated_income": stated_income,
        "total_allocated": total_allocated,
        "variance": variance,
        "allocations": found_allocations,
        "flaw_message": flaw_msg
    }


def audit_geography_and_logistics(text: str, default_city: str = "") -> List[str]:
    """
    Audits Indonesian geography, public transit facts, and urban logistics.
    Returns list of specific logic flaws detected.
    """
    flaws = []
    text_lower = text.lower()

    # 1. Check Non-KRL Cities transit hallucinations
    city_found = default_city.lower() if default_city else ""
    if not city_found:
        for c in NON_KRL_CITIES:
            if re.search(r"\b" + c + r"\b", text_lower):
                city_found = c
                break

    if city_found in NON_KRL_CITIES:
        # Check if text claims riding KRL / JakLingko / MRT in a non-transit city
        if re.search(r"\b(krl|mrt|jaklingko|lrt jabodebek)\b", text_lower):
            flaws.append(
                f"HALUSINASI GEOGRAFI: Menyebut naik KRL/MRT/JakLingko di {city_found.title()}. "
                f"Kota {city_found.title()} TIDAK memiliki KRL/MRT! "
                "Gunakan 'KA Lokal/Prameks/Commuter Surabaya', 'Trans Metro', 'Angkot', atau 'Ojol'."
            )

    # 2. Check Absurd Sudirman/Thamrin Boarding Price
    if re.search(r"\b(sudirman|thamrin|kuningan|scbd)\b", text_lower):
        m_kos = re.search(r"(?:kos|sewa kamar)\s*(?:rp\.?\s*)?([0-9.,]+\s*(?:jt|juta|rb|ribu|k)?)", text_lower)
        if m_kos:
            val = parse_rupiah_amount(m_kos.group(1))
            if val and val < 1_000_000:
                flaws.append(
                    f"HARGA TIDAK REALISTIS: Mengklaim kos Rp {val:,} di kawasan premium "
                    "(Sudirman/Thamrin/Kuningan/SCBD). Minimal kos layak di ring 1 adalah Rp 1.5jt - 2.5jt!"
                )

    # 3. Check Dual Rent & Mortgage Conflict without Context
    has_kontrakan = bool(re.search(r"\b(sewa kontrakan|bayar kontrakan|kontrakan setahun)\b", text_lower))
    has_kpr = bool(re.search(r"\b(nyicil kpr|cicilan kpr|angsuran rumah)\b", text_lower))
    if has_kontrakan and has_kpr and not re.search(r"\b(rumah ortu|dikontrakin lagi|renovasi|keluarga)\b", text_lower):
        flaws.append(
            "PLOT HOLE KONTRAK & KPR: Mengklaim bayar sewa kontrakan sekaligus nyicil KPR "
            "tanpa penjelasan logis (misal rumah KPR masih inden atau rumah untuk orang tua)."
        )

    return flaws


def audit_story_content(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main Gateway Truth Verifier for Threads Posts.
    Combines math audit and reality checks into an executive verdict.
    """
    slides = payload.get("slides") or []
    topic = payload.get("topic", "")
    city = payload.get("city", "")

    full_text = f"{topic}\n" + "\n".join(slides)

    math_result = audit_financial_math(full_text)
    geo_flaws = audit_geography_and_logistics(full_text, default_city=city)

    all_flaws = []
    if not math_result.get("is_valid"):
        all_flaws.append(math_result.get("flaw_message"))
    all_flaws.extend(geo_flaws)

    is_approved = len(all_flaws) == 0

    return {
        "is_approved": is_approved,
        "math_audit": math_result,
        "logic_flaws": all_flaws,
        "critique": "; ".join(all_flaws) if all_flaws else "Hitungan matematis akurat dan logika geografi 100% realistis."
    }
